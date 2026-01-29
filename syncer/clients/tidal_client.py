"""Tidal API client with search, playlist management, and favorites."""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import tidalapi

from syncer.config import load_tidal_session, save_tidal_session
from syncer.constants import (
    SEARCH_RESULTS_LIMIT,
    WORDS_MATCH_THRESHOLD,
    LIKED_TRACKS_FETCH_LIMIT,
    DEFAULT_LIKE_WORKERS,
    get_logger,
)
from syncer.models import Track
from syncer.retry import retry_with_backoff

logger = get_logger("tidal")


class MatchType(Enum):
    EXACT = "exact"
    FUZZY = "fuzzy"
    TITLE_ONLY = "title_only"


@dataclass
class SearchResult:
    track: tidalapi.Track
    match_type: MatchType


def normalize(text: str) -> str:
    """Remove special chars and extra spaces for comparison."""
    text = re.sub(r"[^\w\s]", " ", text.lower())
    return " ".join(text.split())


def make_track_key(artist: str, title: str) -> str:
    """Create normalized key for track comparison."""
    return f"{normalize(artist)}:{normalize(title)}"


def clean_for_search(text: str) -> str:
    """Remove common suffixes that interfere with search."""
    # Remove content in parentheses/brackets: (feat. X), (Remix), [Live], etc.
    text = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", "", text)
    # Remove common suffixes
    patterns = [
        r"\s*-\s*single\s*version.*$",
        r"\s*-\s*remaster.*$",
        r"\s*-\s*mono\s*$",
        r"\s*-\s*stereo\s*$",
        r"\s*-\s*live.*$",
        r"\s*-\s*acoustic.*$",
        r"\s*-\s*bonus\s*track.*$",
        r"\s*-\s*deluxe.*$",
        r"\s*feat\..*$",
        r"\s*ft\..*$",
    ]
    for pattern in patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)
    return text.strip()


def words_match(needle: str, haystack: str) -> bool:
    """Check if main words from needle are in haystack."""
    needle_words = set(normalize(needle).split())
    haystack_words = set(normalize(haystack).split())
    if not needle_words:
        return False
    matches = needle_words & haystack_words
    return len(matches) >= len(needle_words) * WORDS_MATCH_THRESHOLD


class TidalClient:
    def __init__(self):
        self.session = tidalapi.Session()
        self._liked_tracks_cache: Optional[set[int]] = None
        self._playlist_tracks_cache: dict[str, list] = {}

    def login(self) -> bool:
        """Login to Tidal via OAuth or saved session."""
        # Try to load saved session first
        if load_tidal_session(self.session):
            logger.info("Используем сохранённую сессию Tidal")
            print("Используем сохранённую сессию Tidal")
            return True

        # Otherwise do OAuth login
        logger.info("Начинаем OAuth авторизацию Tidal")
        login, future = self.session.login_oauth()
        url = login.verification_uri_complete
        if not url.startswith("http"):
            url = f"https://{url}"
        print(f"\nПерейдите по ссылке для авторизации в Tidal:\n{url}\n")
        future.result()

        if self.session.check_login():
            save_tidal_session(self.session)
            logger.info("Авторизация Tidal успешна, сессия сохранена")
            print("Сессия сохранена")
            return True

        logger.error("Авторизация Tidal не удалась")
        return False

    def search_track(self, track: Track, exact_only: bool = False) -> Optional[SearchResult]:
        """Search for a track in Tidal using multiple strategies."""
        # Clean artist and title for better search
        clean_artist = clean_for_search(track.artist)
        clean_title = clean_for_search(track.title)

        # Build search strategies
        strategies = [
            f"{track.artist} {track.title}",  # Original
            f"{clean_artist} {clean_title}",  # Cleaned
            track.title,  # Title only
            clean_title,  # Clean title only
        ]

        # Artist + first word of title (safe check for empty title)
        clean_title_words = clean_title.split() if clean_title else []
        if clean_artist and clean_title_words:
            strategies.append(f"{clean_artist} {clean_title_words[0]}")

        # Remove duplicates while preserving order
        seen = set()
        unique_strategies = []
        for s in strategies:
            if s and s not in seen:
                seen.add(s)
                unique_strategies.append(s)

        for query in unique_strategies:
            result = self._search_with_query(query, track, exact_only)
            if result:
                logger.debug(f"Найден трек: {track.artist} - {track.title} -> {result.match_type.value}")
                return result

        logger.debug(f"Трек не найден: {track.artist} - {track.title}")
        return None

    @retry_with_backoff(max_attempts=3)
    def _search_with_query(self, query: str, track: Track, exact_only: bool = False) -> Optional[SearchResult]:
        """Execute search query with retry logic."""
        try:
            results = self.session.search(query, models=[tidalapi.Track], limit=SEARCH_RESULTS_LIMIT)
        except Exception as e:
            logger.warning(f"Ошибка поиска '{query}': {e}")
            raise  # Re-raise for retry logic

        if not results or "tracks" not in results or not results["tracks"]:
            return None

        # First pass: exact matching
        for result in results["tracks"]:
            result_artist = result.artist.name if result.artist else ""
            result_title = result.name if result.name else ""

            artist_match = (
                normalize(track.artist) in normalize(result_artist)
                or normalize(result_artist) in normalize(track.artist)
            )
            title_match = (
                normalize(track.title) in normalize(result_title)
                or normalize(result_title) in normalize(track.title)
            )

            if artist_match and title_match:
                return SearchResult(result, MatchType.EXACT)

        # Skip fuzzy matching in exact_only mode
        if exact_only:
            return None

        # Second pass: fuzzy word matching
        for result in results["tracks"]:
            result_artist = result.artist.name if result.artist else ""
            result_title = result.name if result.name else ""

            if words_match(track.title, result_title) and words_match(track.artist, result_artist):
                return SearchResult(result, MatchType.FUZZY)

        # Third pass: just title match
        for result in results["tracks"]:
            result_title = result.name if result.name else ""
            if normalize(track.title) == normalize(result_title):
                return SearchResult(result, MatchType.TITLE_ONLY)

        return None

    def find_playlist_by_name(self, name: str) -> Optional[tidalapi.Playlist]:
        """Find user's playlist by name."""
        try:
            playlists = self.session.user.playlists()
            for pl in playlists:
                if pl.name == name:
                    return pl
            return None
        except Exception as e:
            logger.error(f"Ошибка получения плейлистов: {e}")
            return None

    def get_playlist_tracks(self, playlist: tidalapi.Playlist) -> list:
        """Get playlist tracks with caching."""
        playlist_id = str(playlist.id)
        if playlist_id not in self._playlist_tracks_cache:
            try:
                self._playlist_tracks_cache[playlist_id] = list(playlist.tracks())
            except Exception as e:
                logger.error(f"Ошибка загрузки треков плейлиста: {e}")
                return []
        return self._playlist_tracks_cache[playlist_id]

    def invalidate_playlist_cache(self, playlist: tidalapi.Playlist) -> None:
        """Clear cached tracks for a playlist."""
        playlist_id = str(playlist.id)
        self._playlist_tracks_cache.pop(playlist_id, None)

    def get_playlist_track_keys(self, playlist: tidalapi.Playlist) -> set[str]:
        """Returns set of normalized 'artist:title' keys for tracks in playlist."""
        keys = set()
        for track in self.get_playlist_tracks(playlist):
            artist = track.artist.name if track.artist else ""
            title = track.name if track.name else ""
            keys.add(make_track_key(artist, title))
        return keys

    def get_playlist_track_ids(self, playlist: tidalapi.Playlist) -> list[int]:
        """Returns list of track IDs in playlist."""
        return [track.id for track in self.get_playlist_tracks(playlist)]

    def get_playlist_tracks_with_indices(self, playlist: tidalapi.Playlist) -> list[tuple[int, str, str, int]]:
        """Returns list of (index, artist, title, track_id) for tracks in playlist."""
        result = []
        for idx, track in enumerate(self.get_playlist_tracks(playlist)):
            artist = track.artist.name if track.artist else ""
            title = track.name if track.name else ""
            result.append((idx, artist, title, track.id))
        return result

    def create_playlist(self, name: str, description: str = "") -> tidalapi.Playlist:
        """Create a new playlist."""
        logger.info(f"Создаём плейлист: {name}")
        return self.session.user.create_playlist(name, description)

    def add_tracks_to_playlist(
        self, playlist: tidalapi.Playlist, track_ids: list[int]
    ) -> None:
        """Add tracks to playlist."""
        if track_ids:
            try:
                playlist.add(track_ids)
                self.invalidate_playlist_cache(playlist)
                logger.info(f"Добавлено {len(track_ids)} треков в плейлист")
            except Exception as e:
                logger.error(f"Ошибка добавления треков: {e}")

    def remove_tracks_from_playlist(
        self, playlist: tidalapi.Playlist, track_indices: list[int]
    ) -> None:
        """Remove tracks by their index in the playlist."""
        if not track_indices:
            return

        # Sort in reverse to remove from end first (indices don't shift)
        for idx in sorted(track_indices, reverse=True):
            try:
                playlist.remove_by_index(idx)
            except Exception as e:
                logger.warning(f"Не удалось удалить трек с индексом {idx}: {e}")

        self.invalidate_playlist_cache(playlist)
        logger.info(f"Удалено {len(track_indices)} треков из плейлиста")

    def get_liked_track_ids(self) -> set[int]:
        """Get IDs of tracks already in user's favorites (cached)."""
        if self._liked_tracks_cache is not None:
            return self._liked_tracks_cache

        try:
            liked_tracks = self.session.user.favorites.tracks(limit=LIKED_TRACKS_FETCH_LIMIT)
            self._liked_tracks_cache = {t.id for t in liked_tracks}
            logger.debug(f"Загружено {len(self._liked_tracks_cache)} лайкнутых треков")
            return self._liked_tracks_cache
        except Exception as e:
            logger.error(f"Ошибка загрузки лайкнутых треков: {e}")
            return set()

    def invalidate_likes_cache(self) -> None:
        """Clear the liked tracks cache."""
        self._liked_tracks_cache = None

    def like_tracks(self, track_ids: list[int], progress_callback=None, workers: int = DEFAULT_LIKE_WORKERS) -> int:
        """Add tracks to user's favorites. Returns number of newly liked tracks."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # Filter out already liked tracks
        already_liked = self.get_liked_track_ids()
        to_like = [tid for tid in track_ids if tid not in already_liked]

        if not to_like:
            return 0

        liked = 0
        completed = 0
        total = len(to_like)

        def like_one(track_id: int) -> bool:
            try:
                self.session.user.favorites.add_track(track_id)
                return True
            except Exception as e:
                logger.warning(f"Не удалось лайкнуть трек {track_id}: {e}")
                return False

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(like_one, tid): tid for tid in to_like}
            for future in as_completed(futures):
                completed += 1
                if future.result():
                    liked += 1
                if progress_callback:
                    progress_callback(completed, total)

        # Invalidate cache after liking
        self.invalidate_likes_cache()
        logger.info(f"Лайкнуто {liked} новых треков")
        return liked
