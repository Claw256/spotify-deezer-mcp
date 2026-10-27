import json

import httpx
import pytest

from spotify_deezer_mcp import config, deezer_client as dz


def _transport(log, user_id="42"):
    def handler(req: httpx.Request) -> httpx.Response:
        method = req.url.params["method"]
        body = json.loads(req.content or b"{}")
        log.append((method, req.url.params["api_token"], body, req.headers.get("cookie")))
        if method == "deezer.getUserData":
            return httpx.Response(200, json={"error": {}, "results": {"USER": {"USER_ID": user_id}, "checkForm": "tok"}})
        return httpx.Response(200, json={"error": [], "results": 777})
    return httpx.MockTransport(handler)


def test_create_playlist_arl_flow(monkeypatch):
    monkeypatch.setattr(config, "DEEZER_ARL", "secretarl")
    monkeypatch.setattr(httpx, "get", lambda *a, **k: httpx.Response(200, json={"error": {"type": "DataException"}}))
    log = []
    res = dz.create_playlist_arl("T", [1, 2], "d", public=False, transport=_transport(log))
    assert res == {"id": 777, "url": "https://www.deezer.com/playlist/777", "public": False}
    assert log[1][0] == "playlist.create" and log[1][1] == "tok"
    assert log[1][2]["songs"] == [[1, 0], [2, 0]] and log[1][2]["status"] == 2
    assert "arl=secretarl" in log[1][3]


def test_rejected_arl(monkeypatch):
    monkeypatch.setattr(config, "DEEZER_ARL", "bad")
    with pytest.raises(dz.DeezerError, match="rejected"):
        dz.create_playlist_arl("T", [1], transport=_transport([], user_id="0"))
