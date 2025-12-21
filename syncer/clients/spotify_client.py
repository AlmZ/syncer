import os
from typing import Iterable

import spotipy
from spotipy.oauth2 import SpotifyOAuth

from syncer.models import Track


class SpotifyClient:
    """Thin wrapper around Spotify API tailored for playlist syncing."""

    def __init__(self, scope: str | None = None):
        scope = scope or "playlist-read-private playlist-modify-private playlist-modify-public"
        self.client = spotipy.Spotify(
            auth_manager=SpotifyOAuth(
                scope=scope,
                client_id=os.environ.get("SPOTIFY_CLIENT_ID"),
                client_secret=os.environ.get("SPOTIFY_CLIENT_SECRET"),
                redirect_uri=os.environ.get("SPOTIFY_REDIRECT_URI", "http://localhost:8080/callback"),
                cache_path=os.environ.get("SPOTIFY_TOKEN_CACHE", ".spotify-token-cache"),
                open_browser=False,
            )
        )

    def get_playlist_tracks(self, playlist_id: str) -> list[Track]:
        results = self.client.playlist_items(playlist_id, additional_types=("track",))
        tracks = self._extract_tracks(results)
        while results["next"]:
            results = self.client.next(results)
            tracks.extend(self._extract_tracks(results))
        return Track.deduplicate(tracks)

    def add_tracks(self, playlist_id: str, tracks: Iterable[Track]) -> None:
        uris = [f"spotify:track:{track.provider_id}" for track in tracks]
        if uris:
            self.client.playlist_add_items(playlist_id, uris)

    @staticmethod
    def _extract_tracks(results: dict) -> list[Track]:
        extracted: list[Track] = []
        for item in results.get("items", []):
            track = item.get("track")
            if not track:
                continue
            name = track.get("name")
            artists = tuple(artist.get("name", "") for artist in track.get("artists", []))
            track_id = track.get("id")
            if not name or not track_id:
                continue
            extracted.append(Track(name=name, artists=artists, provider_id=track_id))
        return extracted
