import os
from typing import Iterable

from yandex_music import Client

from syncer.models import Track


class YandexMusicClient:
    """Wrapper around Yandex Music API for playlist syncing."""

    def __init__(self, token: str | None = None):
        token = token or os.environ.get("YANDEX_MUSIC_TOKEN")
        if not token:
            raise ValueError("YANDEX_MUSIC_TOKEN is required")
        self.client = Client(token).init()

    def get_playlist_tracks(self, user_id: str, playlist_kind: int) -> list[Track]:
        playlist = self.client.users_playlists(playlist_kind, user_id=user_id)
        tracks = [
            Track(
                name=track.track.title,
                artists=tuple(artist.name for artist in track.track.artists or ()),
                provider_id=str(track.track.track_id),
            )
            for track in playlist.tracks
            if track.track
        ]
        return Track.deduplicate(tracks)

    def add_tracks(self, user_id: str, playlist_kind: int, tracks: Iterable[Track]) -> None:
        ids = [track.provider_id for track in tracks]
        if ids:
            self.client.users_playlists_insert_track(user_id, playlist_kind, ids)
