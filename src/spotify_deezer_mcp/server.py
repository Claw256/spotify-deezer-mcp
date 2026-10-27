"""FastMCP server: Spotify discovery + tagging, similarity playlist builder, Deezer export."""
import uuid

from mcp.server.fastmcp import FastMCP

from . import config
from . import deezer_client as dz
from . import features, matcher, spotify_client as sp

mcp = FastMCP("spotify-deezer-playlist")

_drafts: dict[str, dict] = {}  # draft_id -> {"name", "seed", "tracks"}


def _tag(tracks: list[dict], with_features: bool = True) -> list[dict]:
    """Attach BPM/key/energy/genres to normalised track dicts."""
    if not tracks:
        return tracks
    feats = features.get_features(tracks) if with_features else {}
    genres = sp.artist_genres([a for t in tracks for a in t["artist_ids"]])
    out = []
    for t in tracks:
        f = feats.get(t["id"], {})
        g = sorted({x for a in t["artist_ids"] for x in genres.get(a, [])})
        out.append({**t, **f, "genres": g})
    return out


def _brief(t: dict) -> dict:
    keep = ("id", "name", "artists", "duration_sec", "bpm", "key", "camelot", "energy", "valence", "genres", "isrc")
    return {k: t.get(k) for k in keep}


@mcp.tool()
def search_playlists(query: str, limit: int = 10) -> list[dict]:
    """Search Spotify playlists (e.g. "Techno Mix", "drum and bass"). Algorithmic Mix
    playlists may not be visible to API apps; results are best-effort."""
    return sp.search_playlists(query, limit)


@mcp.tool()
def search_tracks(query: str, limit: int = 10) -> list[dict]:
    """Search Spotify tracks to find a seed. Supports filters, e.g. 'artist:Jon Hopkins track:Open Eye Signal'."""
    return [_brief(t) for t in _tag(sp.search_tracks(query, limit), with_features=False)]


@mcp.tool()
def get_playlist_tracks(playlist_id: str, limit: int = 50, with_features: bool = True) -> list[dict]:
    """List a Spotify playlist's tracks with BPM, key (+Camelot), energy, valence, genres and length."""
    return [_brief(t) for t in _tag(sp.playlist_tracks(playlist_id, limit), with_features)]


@mcp.tool()
def get_track_features(track_id: str) -> dict:
    """Tags for one Spotify track: BPM, key, Camelot code, energy, valence, danceability, genres, length."""
    return _tag([sp.get_track(track_id)])[0]


def _gather_candidates(seed: dict, genres: list[str], per_query: int) -> dict[str, dict]:
    pool: dict[str, dict] = {}

    def add(tracks: list[dict]) -> None:
        for t in tracks:
            if t["id"] != seed["id"]:
                pool.setdefault(t["id"], t)

    for g in genres[:3]:
        for fn in (
            lambda: sp.search_tracks(f'genre:"{g}"', per_query),
            lambda: [t for p in sp.search_playlists(f"{g} Mix", 3)[:2] for t in sp.playlist_tracks(p["id"], 50)],
        ):
            try:
                add(fn())
            except Exception:  # endpoint blocked/unavailable for this app: skip source
                continue

    # Deezer related artists -> their top tracks -> resolve on Spotify
    artist = dz.find_artist(seed["artists"].split(",")[0].strip())
    if artist:
        for rel in dz.related_artists(artist["id"], 10):
            for top in dz.artist_top_tracks(rel["id"], 2):
                try:
                    add(sp.search_tracks(f'artist:"{rel["name"]}" track:"{top["title"]}"', 1))
                except Exception:
                    continue
    return pool


@mcp.tool()
def build_similar_playlist(
    seed_track_id: str,
    track_count: int = 20,
    bpm_tolerance: float = 6.0,
    key_mode: str = "compatible",
    unique_artists: bool = True,
    allow_half_double_time: bool = True,
    playlist_name: str = "",
) -> dict:
    """Build a draft playlist around a seed Spotify track: tracks from DIFFERENT artists that match
    its BPM, key and genre/vibe. key_mode: 'strict' (same key), 'compatible' (same or Camelot-adjacent),
    'ignore'. Returns a draft_id to pass to export_to_deezer. Nothing is saved to Deezer here."""
    seed = _tag([sp.get_track(seed_track_id)])[0]
    seed_genres = set(seed["genres"])
    pool = _gather_candidates(seed, sorted(seed_genres), per_query=max(50, track_count * 3))
    tagged = _tag(list(pool.values()))

    scored = []
    for c in tagged:
        s = matcher.score_candidate(
            seed, c, seed_genres, set(c["genres"]),
            bpm_tolerance=bpm_tolerance, allow_half_double=allow_half_double_time, key_mode=key_mode,
        )
        if s is not None:
            scored.append({**c, "score": round(s, 3)})
    picked = matcher.select_diverse(scored, track_count, set(seed["artist_ids"]), unique_artists)

    name = playlist_name or f"Like {seed['name']} - {seed['artists'].split(',')[0]}"
    draft_id = uuid.uuid4().hex[:8]
    result = {"seed": _brief(seed), "tracks": [{**_brief(t), "score": t["score"]} for t in picked]}
    _drafts[draft_id] = {"name": name, "tracks": [seed, *picked]}
    return {
        "draft_id": draft_id,
        "name": name,
        "candidates_considered": len(tagged),
        "tracks_without_bpm_or_key": sum(1 for c in tagged if not c.get("bpm") or not c.get("camelot")),
        "short_by": max(0, track_count - len(picked)),
        **result,
    }


@mcp.tool()
def deezer_auth_status() -> dict:
    """Whether a valid Deezer token is stored."""
    return dz.auth_status()


@mcp.tool()
def deezer_authorize() -> dict:
    """Run the Deezer OAuth flow (opens a browser; waits up to 3 minutes for the redirect)."""
    return dz.authorize()


@mcp.tool()
def export_to_deezer(draft_id: str, name: str = "", description: str = "", public: bool = False,
                     include_seed: bool = True) -> dict:
    """Create a Deezer playlist from a draft made by build_similar_playlist. Tracks are matched by ISRC,
    falling back to artist+title search; unmatched tracks are reported."""
    draft = _drafts.get(draft_id)
    if not draft:
        raise ValueError(f"Unknown draft_id {draft_id!r}")
    tracks = draft["tracks"] if include_seed else draft["tracks"][1:]
    matched, unmatched = dz.match_tracks(tracks)
    title = name or draft["name"]
    result = {
        "added": len(matched),
        "unmatched": [f"{t['artists']} - {t['name']}" for t in unmatched],
    }
    ids = [m["deezer_id"] for m in matched]
    desc = description or "Built by spotify-deezer-mcp"
    if config.DEEZER_ARL:
        return {**dz.create_playlist_arl(title, ids, desc, public), **result}
    if dz.load_token():
        return {**dz.create_playlist(title, ids, desc, public), **result}
    # No Deezer app/token (public API is read-only): write a file instead.
    return {**dz.write_export(title, matched), **result,
            "note": "No Deezer token, so no playlist was created. Import the CSV via a transfer tool or add the tracks by hand."}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
