# Spotify ↔️ Yandex Music playlist sync

Local-first Python service that syncs tracks between a Spotify playlist and a Yandex Music playlist. The script normalizes tracks by title and artist names, deduplicates them, and adds any missing tracks in the chosen direction or both ways.

## Setup

1. Create a virtual environment and install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Create a `.env` file with your credentials and identifiers:

```env
SPOTIFY_CLIENT_ID=your_spotify_client_id
SPOTIFY_CLIENT_SECRET=your_spotify_client_secret
SPOTIFY_REDIRECT_URI=http://localhost:8080/callback  # optional
SPOTIFY_TOKEN_CACHE=.spotify-token-cache            # optional path for cached OAuth token

YANDEX_MUSIC_TOKEN=your_yandex_music_token
```

- Spotify requires a token with `playlist-read-private`, `playlist-modify-private`, and `playlist-modify-public` scopes. The first run will prompt you to authorize in the browser and store the token in the cache file.
- Yandex Music tokens can be generated from https://music.yandex.com/settings/developers.

## Usage

Run the sync script with playlist identifiers:

```bash
python sync.py \
  --spotify-playlist <spotify_playlist_id> \
  --yandex-user <yandex_user_id> \
  --yandex-kind <yandex_playlist_kind> \
  --direction both
```

- `--direction` can be `both` (default), `spotify-to-yandex`, or `yandex-to-spotify`.
- The script will report how many tracks were added to each service.

## How it works

- `syncer/clients/spotify_client.py` and `syncer/clients/yandex_client.py` wrap the respective APIs and return normalized `Track` objects.
- `syncer/service.py` computes differences between playlists using a normalized signature (track name + artists) and issues add operations in the requested direction.

## Troubleshooting

- If OAuth for Spotify cannot open a browser automatically, copy the displayed URL into a browser manually. The resulting redirect URL should be pasted back into the terminal when requested by the library.
- Ensure your Spotify app has the redirect URI configured to match `SPOTIFY_REDIRECT_URI`.
- Yandex playlist `kind` is the numeric identifier visible in the playlist URL.
