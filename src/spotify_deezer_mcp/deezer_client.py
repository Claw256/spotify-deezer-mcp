"""Deezer API client: public lookups plus OAuth-protected playlist creation.

The zaosoula/deezer-public-api wrapper only covers read-only endpoints, so this calls
the REST API (https://api.deezer.com) directly.
"""
import difflib
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import httpx

from . import config

API = "https://api.deezer.com"
OAUTH = "https://connect.deezer.com/oauth"
TOKEN_FILE = config.CACHE_DIR / "deezer_token.json"
PERMS = "basic_access,manage_library,offline_access"


class DeezerError(RuntimeError):
    pass


def _get(path: str, **params) -> dict:
    r = httpx.get(f"{API}{path}", params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and "error" in data:
        raise DeezerError(str(data["error"]))
    return data


# ---------- auth ----------

def load_token() -> str | None:
    try:
        return json.loads(TOKEN_FILE.read_text())["access_token"]
    except (OSError, KeyError, ValueError):
        return None


def auth_status() -> dict:
    token = load_token()
    if not token:
        return {"authorized": False}
    try:
        me = _get("/user/me", access_token=token)
        return {"authorized": True, "user": me.get("name")}
    except (DeezerError, httpx.HTTPError):
        return {"authorized": False, "note": "stored token rejected"}


def authorize(timeout: int = 180) -> dict:
    """Open the browser for Deezer consent and catch the redirect on a local server."""
    if not (config.DEEZER_APP_ID and config.DEEZER_APP_SECRET):
        raise DeezerError("DEEZER_APP_ID / DEEZER_APP_SECRET missing in .env")
    redirect = urlparse(config.DEEZER_REDIRECT_URI)
    box: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            qs = parse_qs(urlparse(self.path).query)
            box["code"] = (qs.get("code") or [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Deezer authorised - you can close this tab.")

        def log_message(self, *a):
            pass

    server = HTTPServer((redirect.hostname, redirect.port), Handler)
    server.timeout = timeout
    url = f"{OAUTH}/auth.php?" + httpx.QueryParams(
        app_id=config.DEEZER_APP_ID, redirect_uri=config.DEEZER_REDIRECT_URI, perms=PERMS
    ).__str__()
    webbrowser.open(url)
    t = threading.Thread(target=server.handle_request)
    t.start()
    t.join(timeout)
    server.server_close()
    if not box.get("code"):
        raise DeezerError(f"No authorisation code received. Open manually: {url}")
    r = httpx.get(
        f"{OAUTH}/access_token.php",
        params={
            "app_id": config.DEEZER_APP_ID,
            "secret": config.DEEZER_APP_SECRET,
            "code": box["code"],
            "output": "json",
        },
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    if "access_token" not in data:
        raise DeezerError(f"Token exchange failed: {r.text}")
    TOKEN_FILE.write_text(json.dumps(data))
    return auth_status()


def _require_token() -> str:
    token = load_token()
    if not token:
        raise DeezerError("Not authorised. Call deezer_authorize first.")
    return token


# ---------- lookups ----------

def track_by_isrc(isrc: str) -> dict | None:
    try:
        return _get(f"/track/isrc:{isrc}")
    except (DeezerError, httpx.HTTPError):
        return None


def search_track(title: str, artist: str) -> dict | None:
    """Best fuzzy match for artist+title, or None if nothing is close enough."""
    try:
        res = _get("/search", q=f'artist:"{artist}" track:"{title}"', limit=10).get("data", [])
        if not res:
            res = _get("/search", q=f"{artist} {title}", limit=10).get("data", [])
    except (DeezerError, httpx.HTTPError):
        return None
    want = f"{artist} {title}".lower()
    best, best_r = None, 0.0
    for t in res:
        got = f"{t['artist']['name']} {t['title']}".lower()
        ratio = difflib.SequenceMatcher(None, want, got).ratio()
        if ratio > best_r:
            best, best_r = t, ratio
    return best if best_r >= 0.6 else None


def find_artist(name: str) -> dict | None:
    try:
        res = _get("/search/artist", q=name, limit=1).get("data", [])
    except (DeezerError, httpx.HTTPError):
        return None
    return res[0] if res else None


def related_artists(artist_id: int, limit: int = 15) -> list[dict]:
    try:
        return _get(f"/artist/{artist_id}/related", limit=limit).get("data", [])
    except (DeezerError, httpx.HTTPError):
        return []


def artist_top_tracks(artist_id: int, limit: int = 5) -> list[dict]:
    try:
        return _get(f"/artist/{artist_id}/top", limit=limit).get("data", [])
    except (DeezerError, httpx.HTTPError):
        return []


def full_track(track_id: int) -> dict | None:
    """Full track object (includes `isrc` and `bpm`, which list endpoints omit)."""
    try:
        return _get(f"/track/{track_id}")
    except (DeezerError, httpx.HTTPError):
        return None


# ---------- playlist export ----------

def match_tracks(tracks: list[dict]) -> tuple[list[dict], list[dict]]:
    """tracks: [{name, artists, isrc}] -> (matched [{...,deezer_id}], unmatched)."""
    matched, unmatched = [], []
    for t in tracks:
        hit = track_by_isrc(t["isrc"]) if t.get("isrc") else None
        if not hit or "id" not in hit:
            hit = search_track(t["name"], t["artists"].split(",")[0].strip())
        (matched if hit else unmatched).append({**t, "deezer_id": hit["id"]} if hit else t)
    return matched, unmatched


def write_export(title: str, matched: list[dict]) -> dict:
    """Write Deezer-matched tracks to exports/<title>.csv (plus .txt of track URLs)."""
    import csv
    import re

    out_dir = config.ROOT / "exports"
    out_dir.mkdir(exist_ok=True)
    stem = re.sub(r'[<>:"/\\|?*]+', "_", title).strip() or "playlist"
    csv_path = out_dir / f"{stem}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Track name", "Artist name", "ISRC", "Deezer ID", "Deezer URL", "BPM", "Key"])
        for m in matched:
            w.writerow([m["name"], m["artists"], m.get("isrc") or "", m["deezer_id"],
                        f"https://www.deezer.com/track/{m['deezer_id']}", m.get("bpm") or "", m.get("camelot") or ""])
    txt_path = out_dir / f"{stem}.txt"
    txt_path.write_text("\n".join(f"https://www.deezer.com/track/{m['deezer_id']}" for m in matched), encoding="utf-8")
    return {"csv": str(csv_path), "track_urls": str(txt_path)}


GW = "https://www.deezer.com/ajax/gw-light.php"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def _gw(client: httpx.Client, method: str, token: str = "", body: dict | None = None):
    """Call an unofficial Deezer web-gateway method using the session cookies on `client`."""
    r = client.post(GW, params={"method": method, "input": "3", "api_version": "1.0", "api_token": token}, json=body or {})
    r.raise_for_status()
    data = r.json()
    err = data.get("error")
    if err:  # {} or [] when ok
        raise DeezerError(f"{method}: {err}")
    return data["results"]


def create_playlist_arl(title: str, track_ids: list[int], description: str = "", public: bool = False,
                        transport: httpx.BaseTransport | None = None) -> dict:
    """Create a playlist with the user's own `arl` login cookie (unofficial; may break if Deezer changes it)."""
    if not config.DEEZER_ARL:
        raise DeezerError("DEEZER_ARL missing in .env")
    with httpx.Client(cookies={"arl": config.DEEZER_ARL}, headers={"User-Agent": _UA}, timeout=30,
                      transport=transport) as c:
        user = _gw(c, "deezer.getUserData")
        if str(user.get("USER", {}).get("USER_ID") or "0") == "0":
            raise DeezerError("arl cookie rejected (expired or invalid) - grab a fresh one from your browser")
        token = user["checkForm"]
        res = _gw(c, "playlist.create", token, {
            "title": title,
            "description": description,
            "status": 1 if public else 2,  # 1 = public, 2 = private (checked below)
            "songs": [[i, 0] for i in track_ids],
        })
    pid = res if isinstance(res, (int, str)) else res.get("PLAYLIST_ID", res)
    # Self-check visibility: private playlists are not readable without a token.
    try:
        is_public = "error" not in httpx.get(f"{API}/playlist/{pid}", timeout=20).json()
    except (httpx.HTTPError, ValueError):
        is_public = None
    return {"id": pid, "url": f"https://www.deezer.com/playlist/{pid}", "public": is_public}


def create_playlist(title: str, track_ids: list[int], description: str = "", public: bool = False) -> dict:
    token = _require_token()
    r = httpx.post(
        f"{API}/user/me/playlists",
        params={"title": title, "access_token": token},
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    if "id" not in data:
        raise DeezerError(f"Playlist creation failed: {data}")
    pid = data["id"]
    if description or public:
        httpx.post(
            f"{API}/playlist/{pid}",
            params={"description": description, "public": str(public).lower(), "access_token": token},
            timeout=20,
        )
    for i in range(0, len(track_ids), 50):
        chunk = ",".join(str(x) for x in track_ids[i : i + 50])
        rr = httpx.post(
            f"{API}/playlist/{pid}/tracks",
            params={"songs": chunk, "access_token": token},
            timeout=30,
        )
        rr.raise_for_status()
    return {"id": pid, "url": f"https://www.deezer.com/playlist/{pid}"}
