"""Yandex Music API client."""

from yandex_music import Client

from syncer.constants import get_logger
from syncer.models import Playlist, Track

logger = get_logger("yandex")


class YandexMusicClient:
    def __init__(self, token: str):
        logger.info("Инициализация клиента Yandex Music")
        self.client = Client(token).init()
        logger.debug("Клиент Yandex Music инициализирован")

    def get_playlists(self) -> list[Playlist]:
        """Get all user playlists including favorites."""
        playlists = []

        # Add "Liked tracks" as a special playlist
        try:
            likes = self.client.users_likes_tracks()
            if likes:
                playlists.append(
                    Playlist(
                        id="favorites",
                        name="Мне нравится",
                        tracks=[],
                        track_count=len(likes),
                    )
                )
                logger.debug(f"Найдено {len(likes)} лайкнутых треков")
        except Exception as e:
            logger.warning(f"Не удалось загрузить лайкнутые треки: {e}")

        # Add regular playlists
        try:
            user_playlists = self.client.users_playlists_list()
            for pl in user_playlists:
                playlists.append(
                    Playlist(
                        id=f"{pl.owner.uid}:{pl.kind}",
                        name=pl.title,
                        tracks=[],
                        track_count=pl.track_count,
                    )
                )
            logger.info(f"Загружено {len(playlists)} плейлистов")
        except Exception as e:
            logger.error(f"Ошибка загрузки плейлистов: {e}")

        return playlists

    def get_playlist_with_tracks(self, playlist_id: str) -> Playlist:
        """Get playlist with all its tracks."""
        if playlist_id == "favorites":
            return self._get_favorites()

        owner_uid, kind = playlist_id.split(":")
        try:
            playlist = self.client.users_playlists(kind=int(kind), user_id=owner_uid)
            tracks = self._extract_tracks(playlist.tracks or [])
            logger.info(f"Загружен плейлист '{playlist.title}' с {len(tracks)} треками")

            return Playlist(
                id=playlist_id,
                name=playlist.title,
                tracks=tracks,
                track_count=len(tracks),
            )
        except Exception as e:
            logger.error(f"Ошибка загрузки плейлиста {playlist_id}: {e}")
            raise

    def _get_favorites(self) -> Playlist:
        """Get user's liked tracks as a playlist."""
        likes = self.client.users_likes_tracks()
        tracks = []

        if likes:
            track_ids = [like.track_id for like in likes]
            logger.debug(f"Загружаем {len(track_ids)} лайкнутых треков")

            try:
                full_tracks = self.client.tracks(track_ids)

                for track in full_tracks:
                    if track:
                        artist_name = track.artists[0].name if track.artists else "Unknown"
                        album_name = track.albums[0].title if track.albums else None
                        duration_sec = track.duration_ms // 1000 if track.duration_ms else None
                        tracks.append(
                            Track(
                                title=track.title,
                                artist=artist_name,
                                album=album_name,
                                duration_sec=duration_sec,
                            )
                        )
            except Exception as e:
                logger.error(f"Ошибка загрузки лайкнутых треков: {e}")
                raise

        logger.info(f"Загружено {len(tracks)} лайкнутых треков")
        return Playlist(
            id="favorites",
            name="Мне нравится",
            tracks=tracks,
            track_count=len(tracks),
        )

    def _extract_tracks(self, track_shorts) -> list[Track]:
        """Extract Track objects from playlist track shorts."""
        tracks = []
        for track_short in track_shorts:
            try:
                track = track_short.track or track_short.fetch_track()
                if track:
                    artist_name = track.artists[0].name if track.artists else "Unknown"
                    album_name = track.albums[0].title if track.albums else None
                    duration_sec = track.duration_ms // 1000 if track.duration_ms else None
                    tracks.append(
                        Track(
                            title=track.title,
                            artist=artist_name,
                            album=album_name,
                            duration_sec=duration_sec,
                        )
                    )
            except Exception as e:
                logger.warning(f"Не удалось загрузить трек: {e}")
                continue
        return tracks
