from dataclasses import dataclass
from typing import Iterable

from syncer.clients.spotify_client import SpotifyClient
from syncer.clients.yandex_client import YandexMusicClient
from syncer.models import Track


@dataclass
class PlaylistMapping:
    spotify_id: str
    yandex_user_id: str
    yandex_kind: int


class SyncDirection:
    BOTH = "both"
    SPOTIFY_TO_YANDEX = "spotify-to-yandex"
    YANDEX_TO_SPOTIFY = "yandex-to-spotify"


class SyncService:
    def __init__(self, spotify_client: SpotifyClient, yandex_client: YandexMusicClient):
        self.spotify = spotify_client
        self.yandex = yandex_client

    def sync(self, mapping: PlaylistMapping, direction: str = SyncDirection.BOTH) -> dict[str, list[Track]]:
        spotify_tracks = self.spotify.get_playlist_tracks(mapping.spotify_id)
        yandex_tracks = self.yandex.get_playlist_tracks(mapping.yandex_user_id, mapping.yandex_kind)

        added_to_spotify: list[Track] = []
        added_to_yandex: list[Track] = []

        if direction in (SyncDirection.BOTH, SyncDirection.YANDEX_TO_SPOTIFY):
            missing_on_spotify = self._diff(target=spotify_tracks, source=yandex_tracks)
            self.spotify.add_tracks(mapping.spotify_id, missing_on_spotify)
            added_to_spotify = missing_on_spotify

        if direction in (SyncDirection.BOTH, SyncDirection.SPOTIFY_TO_YANDEX):
            missing_on_yandex = self._diff(target=yandex_tracks, source=spotify_tracks)
            self.yandex.add_tracks(mapping.yandex_user_id, mapping.yandex_kind, missing_on_yandex)
            added_to_yandex = missing_on_yandex

        return {"spotify": added_to_spotify, "yandex": added_to_yandex}

    @staticmethod
    def _diff(target: Iterable[Track], source: Iterable[Track]) -> list[Track]:
        target_signatures = {track.signature for track in target}
        return [track for track in source if track.signature not in target_signatures]
