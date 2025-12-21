import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

from syncer.clients.spotify_client import SpotifyClient
from syncer.clients.yandex_client import YandexMusicClient
from syncer.service import PlaylistMapping, SyncDirection, SyncService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Two-way sync between Spotify and Yandex Music playlists")
    parser.add_argument("--spotify-playlist", required=True, help="Spotify playlist ID (e.g. 37i9dQZF1DXcBWIGoYBM5M)")
    parser.add_argument("--yandex-user", required=True, help="Yandex Music user ID owning the playlist")
    parser.add_argument("--yandex-kind", required=True, type=int, help="Yandex Music playlist kind")
    parser.add_argument(
        "--direction",
        choices=[SyncDirection.BOTH, SyncDirection.SPOTIFY_TO_YANDEX, SyncDirection.YANDEX_TO_SPOTIFY],
        default=SyncDirection.BOTH,
        help="Choose sync direction",
    )
    parser.add_argument("--env-file", default=".env", help="Path to .env file with credentials")
    return parser.parse_args()


def load_environment(env_file: str) -> None:
    env_path = Path(env_file)
    if env_path.exists():
        load_dotenv(env_path)


def main() -> None:
    args = parse_args()
    load_environment(args.env_file)

    spotify = SpotifyClient()
    yandex = YandexMusicClient()
    mapping = PlaylistMapping(
        spotify_id=args.spotify_playlist,
        yandex_user_id=args.yandex_user,
        yandex_kind=args.yandex_kind,
    )
    service = SyncService(spotify, yandex)
    result = service.sync(mapping, direction=args.direction)

    print("Synced successfully!")
    print(f"Added to Spotify: {len(result['spotify'])} tracks")
    print(f"Added to Yandex Music: {len(result['yandex'])} tracks")


if __name__ == "__main__":
    main()
