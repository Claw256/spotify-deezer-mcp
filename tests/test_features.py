import httpx
import pytest

from spotify_deezer_mcp import config, features


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("C", (0, 1)),
        ("Am", (9, 0)),
        ("C♯m", (1, 0)),
        ("A♭", (8, 1)),
        ("Bb minor", (10, 0)),
        ("F# major", (6, 1)),
        ("", (None, None)),
        (None, (None, None)),
        ("H", (None, None)),
    ],
)
def test_parse_key(raw, expected):
    assert features.parse_key(raw) == expected


def test_getsongbpm_match_and_details(monkeypatch):
    monkeypatch.setattr(config, "GETSONGBPM_API_KEY", "k")
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.path)
        if req.url.path == "/search/":
            return httpx.Response(200, json={"search": [
                {"id": "x1", "title": "Other Song", "artist": {"name": "Maddix"}},
                {"id": "a1", "title": "Acid For Breakfast", "artist": {"name": "Maddix"}},
            ]})
        return httpx.Response(200, json={"song": {"id": "a1", "tempo": "150", "key_of": "F♯m"}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        raw = features._getsongbpm(c, "Acid For Breakfast", "Maddix")
    assert raw == {"tempo": 150.0, "key": 6, "mode": 0}
    assert calls == ["/search/", "/song/"]
    assert features._shape(raw)["camelot"] == "11A"


def test_getsongbpm_wrong_artist_rejected(monkeypatch):
    monkeypatch.setattr(config, "GETSONGBPM_API_KEY", "k")
    handler = lambda req: httpx.Response(200, json={"search": [
        {"id": "z", "title": "Acid For Breakfast", "artist": {"name": "Somebody Else"}, "tempo": "99", "key_of": "C"}]})
    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        assert features._getsongbpm(c, "Acid For Breakfast", "Maddix") is None


def test_no_key_means_no_lookup(monkeypatch):
    monkeypatch.setattr(config, "GETSONGBPM_API_KEY", "")
    assert features._getsongbpm(None, "a", "b") is None
