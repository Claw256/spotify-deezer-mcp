"""Thin wrapper over SpotifyWebApiPython (SpotifyClient) returning plain dicts."""
import threading

from spotifywebapipython import SpotifyClient

from . import config

SCOPE = "playlist-read-private playlist-read-collaborative user-library-read"

_client: SpotifyClient | None = None
_lock = threading.Lock()


def client() -> SpotifyClient:
    """Lazily authorise (PKCE; opens a browser the first time, then uses the token cache)."""
    global _client
    with _lock:
        if _client is None:
            if not config.SPOTIFY_CLIENT_ID:
                raise RuntimeError("SPOTIFY_CLIENT_ID missing in .env")
            c = SpotifyClient(
                tokenStorageDir=str(config.CACHE_DIR),
                tokenStorageFile="spotify_tokens.json",
            )
            redirect = dict(
                redirectUriHost=config.SPOTIFY_REDIRECT_HOST,
                redirectUriPort=config.SPOTIFY_REDIRECT_PORT,
            )
            if config.SPOTIFY_CLIENT_SECRET:
                c.SetAuthTokenAuthorizationCode(
                    config.SPOTIFY_CLIENT_ID, config.SPOTIFY_CLIENT_SECRET, SCOPE, **redirect
                )
            else:
                c.SetAuthTokenAuthorizationCodePKCE(config.SPOTIFY_CLIENT_ID, SCOPE, **redirect)
            _client = c
        return _client


def track_dict(t) -> dict:
    """Normalise a Spotify Track model to a plain dict."""
    artists = list(t.Artists or [])
    ext = getattr(t, "ExternalIds", None)
    return {
        "id": t.Id,
        "name": t.Name,
        "artists": ", ".join(a.Name for a in artists),
        "artist_ids": [a.Id for a in artists],
        "duration_sec": round((t.DurationMS or 0) / 1000),
        "isrc": getattr(ext, "Isrc", None) if ext else None,
        "uri": t.Uri,
    }


def search_tracks(query: str, limit: int = 20) -> list[dict]:
    res = client().SearchTracks(query, limit=min(limit, 50), limitTotal=limit)
    return [track_dict(t) for t in (res.Tracks.Items if res.Tracks else []) if t and t.Id]


def search_playlists(query: str, limit: int = 10) -> list[dict]:
    res = client().SearchPlaylists(query, limit=min(limit, 50), limitTotal=limit)
    out = []
    for p in res.Playlists.Items if res.Playlists else []:
        if not p:  # Spotify returns null entries in playlist search results
            continue
        out.append(
            {
                "id": p.Id,
                "name": p.Name,
                "owner": getattr(p.Owner, "DisplayName", None) if p.Owner else None,
                "track_count": getattr(p.Tracks, "Total", None) if p.Tracks else None,
            }
        )
    return out


def playlist_tracks(playlist_id: str, limit: int = 100) -> list[dict]:
    page = client().GetPlaylistItems(playlist_id, limit=min(limit, 50), limitTotal=limit)
    out = []
    for item in page.Items or []:
        t = getattr(item, "Track", None)
        if t and getattr(t, "Id", None) and getattr(t, "Type", "track") == "track":
            out.append(track_dict(t))
    return out


def get_track(track_id: str) -> dict:
    return track_dict(client().GetTrack(track_id))


def artist_genres(artist_ids: list[str]) -> dict[str, list[str]]:
    """{artist_id: [genres]} (batched, 50 per call)."""
    out: dict[str, list[str]] = {}
    ids = list(dict.fromkeys(i for i in artist_ids if i))
    for i in range(0, len(ids), 50):
        # the library annotates `ids` as a list but requires a comma-separated str
        for a in client().GetArtists(",".join(ids[i : i + 50])) or []:
            if a:
                out[a.Id] = list(a.Genres or [])
    return out
