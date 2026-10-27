from spotify_deezer_mcp.camelot import camelot, key_distance, key_name, key_score
from spotify_deezer_mcp.matcher import bpm_score, score_candidate, select_diverse


def test_camelot_known_keys():
    assert camelot(0, 1) == "8B"   # C major
    assert camelot(9, 0) == "8A"   # A minor (relative of C major)
    assert camelot(1, 0) == "12A"  # C# minor
    assert camelot(-1, 1) is None and camelot(None, 1) is None
    assert key_name(9, 0) == "A minor"


def test_key_distance_and_score():
    assert key_distance("8B", "8B") == 0
    assert key_distance("8B", "8A") == 1   # relative minor
    assert key_distance("8B", "9B") == 1
    assert key_distance("12A", "1A") == 1  # wheel wraps
    assert key_score("8B", None) == 0.5
    assert key_score("8B", "3A") == 0.0


def test_bpm_score_half_double():
    assert bpm_score(140, 140, 6, True) == 1.0
    assert bpm_score(140, 70, 6, True) == 1.0
    assert bpm_score(140, 70, 6, False) == 0.0
    assert bpm_score(None, 120, 6, True) == 0.5


def test_hard_filters():
    seed = {"bpm": 128, "camelot": "8A", "energy": 0.8}
    far_key = {"bpm": 128, "camelot": "3B", "energy": 0.8}
    far_bpm = {"bpm": 150, "camelot": "8A", "energy": 0.8}
    ok = {"bpm": 129, "camelot": "9A", "energy": 0.75}
    assert score_candidate(seed, far_key, set(), set()) is None
    assert score_candidate(seed, far_bpm, set(), set()) is None
    assert score_candidate(seed, ok, set(), set()) > 0.7
    assert score_candidate(seed, ok, set(), set(), key_mode="strict") is None
    assert score_candidate(seed, far_key, set(), set(), key_mode="ignore") is not None


def test_select_diverse_one_per_artist_and_excludes_seed_artist():
    pool = [
        {"id": "1", "artist_ids": ["a"], "score": 0.9},
        {"id": "2", "artist_ids": ["b"], "score": 0.8},
        {"id": "3", "artist_ids": ["b"], "score": 0.7},
        {"id": "4", "artist_ids": ["seed"], "score": 0.95},
        {"id": "5", "artist_ids": ["c"], "score": 0.6},
    ]
    got = select_diverse(pool, 10, {"seed"}, unique_artists=True)
    assert [t["id"] for t in got] == ["1", "2", "5"]
    got = select_diverse(pool, 2, {"seed"}, unique_artists=False)
    assert [t["id"] for t in got] == ["1", "2"]
