"""Audio features (BPM, key, energy...) from ReccoBeats, with SQLite cache.

The Spotify audio-features endpoint is closed to apps created after Nov 2024, so tags
come from ReccoBeats (accepts Spotify track IDs, no auth). Tracks it does not know get
all-None fields; callers can fall back to Deezer's own `bpm`.
"""
import json
import sqlite3
import threading

import httpx

from . import config
from .camelot import camelot, key_name

RECCO_URL = "https://api.reccobeats.com/v1/audio-features"
_BATCH = 40  # ids per request
_FALLBACK_CAP = 60  # max GetSongBPM lookups per call (rate limit: 3000/hour)

_db_lock = threading.Lock()
_db = sqlite3.connect(config.CACHE_DIR / "features.sqlite", check_same_thread=False)
_db.execute("CREATE TABLE IF NOT EXISTS features (id TEXT PRIMARY KEY, data TEXT)")


def _cache_get(ids: list[str]) -> dict[str, dict]:
    with _db_lock:
        out = {}
        for i in range(0, len(ids), 500):
            chunk = ids[i : i + 500]
            q = ",".join("?" * len(chunk))
            for tid, data in _db.execute(f"SELECT id, data FROM features WHERE id IN ({q})", chunk):
                out[tid] = json.loads(data)
        return out


def _cache_put(rows: dict[str, dict]) -> None:
    with _db_lock:
        _db.executemany(
            "INSERT OR REPLACE INTO features VALUES (?, ?)",
            [(k, json.dumps(v)) for k, v in rows.items()],
        )
        _db.commit()


def _shape(raw: dict) -> dict:
    key = raw.get("key")
    mode = raw.get("mode")
    return {
        "bpm": round(raw["tempo"], 1) if raw.get("tempo") else None,
        "key": key_name(key, mode),
        "camelot": camelot(key, mode),
        "energy": raw.get("energy"),
        "danceability": raw.get("danceability"),
        "valence": raw.get("valence"),
        "acousticness": raw.get("acousticness"),
        "instrumentalness": raw.get("instrumentalness"),
        "loudness": raw.get("loudness"),
    }


def _spotify_id(href: str) -> str | None:
    return href.rstrip("/").rsplit("/", 1)[-1] if href else None


GSB_URL = "https://api.getsong.co"
_FLAT_SHARP = {"♯": "#", "♭": "b"}
_ENHARMONIC = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#", "Cb": "B", "Fb": "E", "E#": "F", "B#": "C"}
_PITCH = {n: i for i, n in enumerate(["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"])}


def parse_key(key_of: str | None) -> tuple[int | None, int | None]:
    """'C♯m' / 'Ab' / 'F# minor' -> (pitch class 0-11, mode 1 major / 0 minor)."""
    if not key_of:
        return None, None
    s = key_of.strip()
    for k, v in _FLAT_SHARP.items():
        s = s.replace(k, v)
    low = s.lower()
    minor = low.endswith("minor") or low.endswith("min") or (s.endswith("m") and not low.endswith("maj"))
    root = s[:1].upper() + (s[1] if len(s) > 1 and s[1] in "#b" else "")
    root = _ENHARMONIC.get(root, root)
    if root not in _PITCH:
        return None, None
    return _PITCH[root], 0 if minor else 1


def _norm(s: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _getsongbpm(client: httpx.Client, name: str, artist: str) -> dict | None:
    """Look a song up by artist+title on GetSongBPM; return a ReccoBeats-shaped raw dict or None."""
    if not config.GETSONGBPM_API_KEY:
        return None
    key = {"api_key": config.GETSONGBPM_API_KEY}
    try:
        r = client.get(f"{GSB_URL}/search/", params={**key, "type": "both", "lookup": f"song:{name} artist:{artist}", "limit": 5})
        r.raise_for_status()
        hits = r.json().get("search") or []
        if not isinstance(hits, list):
            return None
        want_t, want_a = _norm(name), _norm(artist)
        for h in hits:
            if _norm(h.get("title", "")) != want_t:
                continue
            if want_a not in _norm((h.get("artist") or {}).get("name", "")):
                continue
            song = h
            if not (song.get("tempo") and song.get("key_of")):
                d = client.get(f"{GSB_URL}/song/", params={**key, "id": h["id"]})
                d.raise_for_status()
                song = d.json().get("song") or {}
            key_i, mode = parse_key(song.get("key_of"))
            tempo = float(song["tempo"]) if song.get("tempo") else None
            if tempo or key_i is not None:
                return {"tempo": tempo, "key": key_i, "mode": mode}
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return None
    return None


def get_features(tracks: list[dict]) -> dict[str, dict]:
    """Return {spotify_id: features} for tracks ({id, name, artists}).

    Sources in order: cache, ReccoBeats (by Spotify id), GetSongBPM (by artist+title).
    Tracks nobody knows map to an all-None dict and are NOT cached, so new releases
    are retried later.
    """
    by_id = {t["id"]: t for t in tracks if t.get("id")}
    ids = list(by_id)
    result = {k: v for k, v in _cache_get(ids).items() if v.get("bpm")}
    missing = [i for i in ids if i not in result]
    fetched: dict[str, dict] = {}
    if missing:
        with httpx.Client(timeout=30) as client:
            for i in range(0, len(missing), _BATCH):
                batch = missing[i : i + _BATCH]
                try:
                    r = client.get(RECCO_URL, params={"ids": ",".join(batch)})
                    r.raise_for_status()
                    for item in r.json().get("content", []):
                        sid = _spotify_id(item.get("href", ""))
                        if sid:
                            fetched[sid] = _shape(item)
                except httpx.HTTPError:
                    continue  # transient: leave unknown for this call
            fetched = {k: v for k, v in fetched.items() if v["bpm"]}
            # Fallback: GetSongBPM by artist+title for tracks ReccoBeats doesn't know (capped per call).
            todo = [i for i in missing if i not in fetched][:_FALLBACK_CAP]
            for sid in todo:
                t = by_id[sid]
                raw = _getsongbpm(client, t["name"], t["artists"].split(",")[0].strip())
                if raw:
                    fetched[sid] = _shape(raw)
        _cache_put(fetched)
        result.update(fetched)
    return {i: result.get(i, _shape({})) for i in ids}
