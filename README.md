# spotify-deezer-mcp

MCP server that lets Claude explore Spotify, build a key/BPM/vibe-matched playlist around a seed track (different
artists only), and export it to Deezer.

## Setup

1. `python -m venv .venv && .venv\Scripts\pip install -e .`
2. Copy `.env.example` to `.env` and fill in the values.
   - Spotify app: add redirect URI `http://127.0.0.1:8080/` (set `SPOTIFY_CLIENT_SECRET` to use the client-secret flow; leave it empty for PKCE).
   - Deezer app: set the redirect URL to `http://127.0.0.1:8081/callback`.
3. Register with Claude Code:
   `claude mcp add spotify-deezer -- D:\Projects\deezer_playlist\.venv\Scripts\python.exe -m spotify_deezer_mcp.server`

The first Spotify call opens a browser for consent; call `deezer_authorize` once for Deezer.

## Tools

| Tool | Purpose |
|---|---|
| `search_playlists`, `search_tracks` | Find playlists / a seed track |
| `get_playlist_tracks` | Tracks with BPM, key, Camelot, energy, valence, genres, length |
| `get_track_features` | Tags for a single track |
| `build_similar_playlist` | Draft playlist from a seed (`track_count`, `bpm_tolerance`, `key_mode`, ...) |
| `deezer_authorize`, `deezer_auth_status` | Deezer OAuth |
| `export_to_deezer` | Create the Deezer playlist from a draft (ISRC match, then fuzzy search) |

## Data sources and limits

- BPM/key/energy come from [ReccoBeats](https://reccobeats.com) (no auth, Spotify IDs), cached in `.cache/features.sqlite`,
  because Spotify closed its audio-features endpoint to apps created after Nov 2024. Tracks it doesn't know have no
  BPM/key; they are scored neutrally and counted in `tracks_without_bpm_or_key`.
- Spotify's Recommendations, Related Artists and algorithmic "Mix" playlists are unavailable to most new apps. Candidates
  come from genre searches, any reachable "<genre> Mix" playlists, and Deezer related-artist top tracks.
- `key_mode`: `strict` (same key), `compatible` (same or Camelot-adjacent), `ignore`.

## Credits

BPM and key data fallback provided by [GetSongBPM](https://getsongbpm.com).
Audio features also from [ReccoBeats](https://reccobeats.com).

## Tests

`.venv\Scripts\python -m pytest`
