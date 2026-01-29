"""Sync service for transferring playlists from Yandex Music to Tidal."""

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

from syncer.clients import TidalClient, YandexMusicClient
from syncer.clients.tidal_client import MatchType, SearchResult, make_track_key
from syncer.constants import (
    ARTIST_SIMILARITY_THRESHOLD,
    DURATION_WARNING_THRESHOLD_SEC,
    DEFAULT_SEARCH_WORKERS,
    get_logger,
)
from syncer.models import MatchStats, Playlist, SyncResult, Track

logger = get_logger("service")


class MatchQuality(Enum):
    GOOD = "good"        # Artist matches (spelling difference)
    MEDIUM = "medium"    # Title matches, different artist
    BAD = "bad"          # Questionable match


def normalize_for_compare(text: str) -> str:
    """Normalize text for comparison."""
    text = re.sub(r"[^\w\s]", " ", text.lower())
    return " ".join(text.split())


def artist_similarity(artist1: str, artist2: str) -> float:
    """Check how similar two artist names are using Jaccard similarity."""
    a1 = set(normalize_for_compare(artist1).split())
    a2 = set(normalize_for_compare(artist2).split())
    if not a1 or not a2:
        return 0.0
    intersection = a1 & a2
    union = a1 | a2
    return len(intersection) / len(union)


def classify_match(original: Track, found_artist: str, found_title: str) -> MatchQuality:
    """Classify match quality based on artist/title similarity."""
    # Check artist similarity
    artist_sim = artist_similarity(original.artist, found_artist)

    # High artist similarity = good match (spelling differences, transliteration)
    if artist_sim >= ARTIST_SIMILARITY_THRESHOLD:
        return MatchQuality.GOOD

    # Check if title is exact match but artist is different
    orig_title = normalize_for_compare(original.title)
    found_title_norm = normalize_for_compare(found_title)
    if orig_title == found_title_norm or orig_title in found_title_norm or found_title_norm in orig_title:
        return MatchQuality.MEDIUM

    return MatchQuality.BAD


@dataclass
class FuzzyMatch:
    index: int
    original: Track
    found_artist: str
    found_title: str
    tidal_id: int
    quality: MatchQuality = MatchQuality.MEDIUM
    found_duration_sec: Optional[int] = None  # Duration of found Tidal track

    @property
    def duration_diff(self) -> Optional[int]:
        """Return absolute difference in seconds, or None if unknown."""
        if self.original.duration_sec is None or self.found_duration_sec is None:
            return None
        return abs(self.original.duration_sec - self.found_duration_sec)

    @property
    def duration_warning(self) -> bool:
        """Return True if duration differs significantly."""
        diff = self.duration_diff
        return diff is not None and diff > DURATION_WARNING_THRESHOLD_SEC


class SyncService:
    def __init__(self, yandex_client: YandexMusicClient, tidal_client: TidalClient):
        self.yandex = yandex_client
        self.tidal = tidal_client

    def sync_playlist(
        self,
        playlist: Playlist,
        tidal_playlist_name: Optional[str] = None,
        progress_callback: Optional[Callable] = None,
        fuzzy_selector: Optional[Callable[[list[FuzzyMatch]], list[int]]] = None,
        workers: int = DEFAULT_SEARCH_WORKERS,
        exact_only: bool = False,
        like_tracks: bool = False,  # Also like tracks in Tidal (for favorites sync)
        cleanup_deleted: bool = False,  # Remove tracks from Tidal that are not in Yandex
        cleanup_selector: Optional[Callable[[list[tuple[str, str]]], list[int]]] = None,
    ) -> SyncResult:
        target_name = tidal_playlist_name or playlist.name
        logger.info(f"Начинаем синхронизацию плейлиста '{target_name}'")

        # Check if playlist already exists in Tidal
        tidal_playlist = self.tidal.find_playlist_by_name(target_name)
        existing_keys: set[str] = set()
        is_delta = False

        if tidal_playlist:
            print("Загружаем существующий плейлист Tidal...")
            existing_keys = self.tidal.get_playlist_track_keys(tidal_playlist)
            logger.info(f"Найдено {len(existing_keys)} существующих треков")
            print(f"Найдено {len(existing_keys)} существующих треков")
            is_delta = True

        # Filter tracks for delta sync using normalized keys
        if existing_keys:
            tracks_to_sync = []
            for track in playlist.tracks:
                key = make_track_key(track.artist, track.title)
                if key not in existing_keys:
                    tracks_to_sync.append(track)
            skipped = len(playlist.tracks) - len(tracks_to_sync)
            logger.debug(f"Пропущено {skipped} уже синхронизированных треков")
        else:
            tracks_to_sync = playlist.tracks
            skipped = 0

        if not tracks_to_sync:
            logger.info("Нет новых треков для синхронизации")
            return SyncResult(
                playlist_name=target_name,
                total_tracks=len(playlist.tracks),
                found_tracks=0,
                not_found_tracks=[],
                skipped_tracks=skipped,
                is_delta=is_delta,
            )

        print(f"Ищем {len(tracks_to_sync)} треков в Tidal ({workers} потоков)...\n")
        logger.info(f"Поиск {len(tracks_to_sync)} треков ({workers} потоков)")

        # Parallel search
        search_results = self._search_parallel(tracks_to_sync, workers, progress_callback, exact_only)
        print("\n")

        # Separate exact matches, fuzzy matches, and not found
        found_track_ids = []
        fuzzy_matches: list[FuzzyMatch] = []
        not_found_tracks = []
        stats = MatchStats()

        for idx, (track, result) in enumerate(search_results):
            if result:
                tidal_track = result.track
                found_artist = tidal_track.artist.name if tidal_track.artist else "?"
                found_title = tidal_track.name if tidal_track.name else "?"
                found_key = make_track_key(found_artist, found_title)

                # Skip if this exact Tidal track is already in playlist
                if found_key in existing_keys:
                    skipped += 1
                    continue

                if result.match_type == MatchType.EXACT:
                    found_track_ids.append(result.track.id)
                    stats.exact += 1
                else:
                    # Fuzzy match - collect for review
                    quality = classify_match(track, found_artist, found_title)
                    # Get duration from Tidal track (in seconds)
                    found_duration = tidal_track.duration if hasattr(tidal_track, 'duration') else None
                    fuzzy_matches.append(FuzzyMatch(
                        index=idx,
                        original=track,
                        found_artist=found_artist,
                        found_title=found_title,
                        tidal_id=result.track.id,
                        quality=quality,
                        found_duration_sec=found_duration,
                    ))
            else:
                not_found_tracks.append(track)

        logger.info(f"Найдено точных: {stats.exact}, fuzzy: {len(fuzzy_matches)}, не найдено: {len(not_found_tracks)}")

        # Let user select which fuzzy matches to include
        if fuzzy_matches and fuzzy_selector:
            selected_indices = fuzzy_selector(fuzzy_matches)
            for match in fuzzy_matches:
                if match.index in selected_indices:
                    found_track_ids.append(match.tidal_id)
                    # Track stats for selected fuzzy matches
                    if match.quality == MatchQuality.GOOD:
                        stats.fuzzy_good += 1
                    elif match.quality == MatchQuality.MEDIUM:
                        stats.fuzzy_medium += 1
                    else:
                        stats.fuzzy_bad += 1
                else:
                    not_found_tracks.append(match.original)
        elif fuzzy_matches:
            # No selector - include all fuzzy matches
            for match in fuzzy_matches:
                found_track_ids.append(match.tidal_id)
                if match.quality == MatchQuality.GOOD:
                    stats.fuzzy_good += 1
                elif match.quality == MatchQuality.MEDIUM:
                    stats.fuzzy_medium += 1
                else:
                    stats.fuzzy_bad += 1

        # Create playlist if doesn't exist
        if not tidal_playlist:
            tidal_playlist = self.tidal.create_playlist(
                name=target_name,
                description="Синхронизировано из Yandex Music",
            )

        # Add tracks to playlist
        if found_track_ids:
            self.tidal.add_tracks_to_playlist(tidal_playlist, found_track_ids)

        # Like tracks in Tidal if requested (for favorites sync)
        liked_count = 0
        if like_tracks and tidal_playlist:
            all_track_ids = self.tidal.get_playlist_track_ids(tidal_playlist)
            if all_track_ids:
                print("Проверяем лайки в Tidal...")

                def like_progress(current, total):
                    percent = current / total * 100
                    print(f"\r♥ Лайкаем: [{current}/{total}] {percent:.0f}%", end="", flush=True)

                liked_count = self.tidal.like_tracks(all_track_ids, like_progress)
                if liked_count > 0:
                    print()  # New line after progress
                else:
                    print("\r♥ Все треки уже лайкнуты" + " " * 20)

        # Cleanup: remove tracks from Tidal that are not in Yandex
        removed_count = 0
        if cleanup_deleted and tidal_playlist:
            removed_count = self._cleanup_deleted_tracks(
                playlist, tidal_playlist, cleanup_selector
            )

        logger.info(f"Синхронизация завершена: добавлено {len(found_track_ids)}, лайкнуто {liked_count}, удалено {removed_count}")

        return SyncResult(
            playlist_name=target_name,
            total_tracks=len(playlist.tracks),
            found_tracks=len(found_track_ids),
            not_found_tracks=not_found_tracks,
            skipped_tracks=skipped,
            is_delta=is_delta,
            match_stats=stats,
            liked_tracks=liked_count,
            removed_tracks=removed_count,
        )

    def _cleanup_deleted_tracks(
        self,
        yandex_playlist: Playlist,
        tidal_playlist,
        cleanup_selector: Optional[Callable[[list[tuple[str, str]]], list[int]]],
    ) -> int:
        """Remove tracks from Tidal that are not in Yandex playlist."""
        # Build set of Yandex track keys (normalized)
        yandex_keys = set()
        for track in yandex_playlist.tracks:
            key = make_track_key(track.artist, track.title)
            yandex_keys.add(key)

        # Get Tidal tracks with indices
        tidal_tracks = self.tidal.get_playlist_tracks_with_indices(tidal_playlist)

        # Find orphaned tracks (in Tidal but not in Yandex)
        orphaned = []
        for idx, artist, title, track_id in tidal_tracks:
            key = make_track_key(artist, title)
            if key not in yandex_keys:
                orphaned.append((idx, artist, title))

        if not orphaned:
            return 0

        logger.info(f"Найдено {len(orphaned)} треков для удаления")

        # Ask user which to remove
        tracks_to_show = [(artist, title) for _, artist, title in orphaned]
        if cleanup_selector:
            selected = cleanup_selector(tracks_to_show)
            indices_to_remove = [orphaned[i][0] for i in selected]
        else:
            indices_to_remove = [idx for idx, _, _ in orphaned]

        if indices_to_remove:
            print(f"Удаляем {len(indices_to_remove)} треков из Tidal...")
            self.tidal.remove_tracks_from_playlist(tidal_playlist, indices_to_remove)

        return len(indices_to_remove)

    def _search_parallel(
        self,
        tracks: list[Track],
        workers: int,
        progress_callback: Optional[Callable],
        exact_only: bool,
    ) -> list[tuple[Track, Optional[SearchResult]]]:
        """Search tracks in parallel using thread pool."""
        results: list[tuple[Track, Optional[SearchResult]]] = []
        completed = 0

        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_track = {
                executor.submit(self.tidal.search_track, track, exact_only): track
                for track in tracks
            }

            for future in as_completed(future_to_track):
                track = future_to_track[future]
                try:
                    result = future.result()
                except Exception as e:
                    logger.warning(f"Ошибка поиска '{track.artist} - {track.title}': {e}")
                    result = None

                results.append((track, result))
                completed += 1

                if progress_callback:
                    progress_callback(completed, len(tracks), track)

        # Restore original order
        track_order = {id(t): i for i, t in enumerate(tracks)}
        results.sort(key=lambda x: track_order[id(x[0])])

        return results
