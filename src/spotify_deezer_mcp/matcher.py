"""Scoring and selection of tracks similar to a seed (pure logic, no I/O)."""
from .camelot import key_score


def bpm_score(seed: float | None, cand: float | None, tolerance: float, allow_half_double: bool) -> float:
    """1.0 at identical BPM, falling linearly to 0 at `tolerance`. Unknown -> 0.5."""
    if not seed or not cand:
        return 0.5
    diffs = [abs(seed - cand)]
    if allow_half_double:
        diffs += [abs(seed - cand * 2), abs(seed * 2 - cand)]
    d = min(diffs)
    return max(0.0, 1.0 - d / tolerance) if tolerance > 0 else float(d == 0)


def vibe_score(seed: dict, cand: dict) -> float:
    """Similarity of energy/valence/danceability (0-1). Unknown -> neutral 0.5."""
    parts = []
    for k in ("energy", "valence", "danceability"):
        a, b = seed.get(k), cand.get(k)
        if a is not None and b is not None:
            parts.append(1.0 - min(1.0, abs(a - b)))
    return sum(parts) / len(parts) if parts else 0.5


def genre_score(seed_genres: set[str], cand_genres: set[str]) -> float:
    if not seed_genres or not cand_genres:
        return 0.5
    return len(seed_genres & cand_genres) / len(seed_genres | cand_genres)


def score_candidate(
    seed: dict,
    cand: dict,
    seed_genres: set[str],
    cand_genres: set[str],
    *,
    bpm_tolerance: float = 6.0,
    allow_half_double: bool = True,
    key_mode: str = "compatible",
) -> float | None:
    """Weighted 0-1 score, or None if a hard filter (key/BPM) excludes the candidate."""
    ks = key_score(seed.get("camelot"), cand.get("camelot"))
    both_keys = bool(seed.get("camelot") and cand.get("camelot"))
    if both_keys and key_mode == "strict" and ks < 1.0:
        return None
    if both_keys and key_mode == "compatible" and ks < 0.8:
        return None
    bs = bpm_score(seed.get("bpm"), cand.get("bpm"), bpm_tolerance, allow_half_double)
    if seed.get("bpm") and cand.get("bpm") and bs <= 0.0:
        return None
    weights = {"bpm": 0.35, "key": 0.25 if key_mode != "ignore" else 0.0, "vibe": 0.25, "genre": 0.15}
    total = sum(weights.values())
    return (
        weights["bpm"] * bs
        + weights["key"] * ks
        + weights["vibe"] * vibe_score(seed, cand)
        + weights["genre"] * genre_score(seed_genres, cand_genres)
    ) / total


def select_diverse(scored: list[dict], count: int, seed_artist_ids: set[str], unique_artists: bool = True) -> list[dict]:
    """Top `count` by score, never the seed's artist, one track per artist if requested."""
    picked, used = [], set(seed_artist_ids)
    for c in sorted(scored, key=lambda x: x["score"], reverse=True):
        ids = set(c["artist_ids"])
        if ids & seed_artist_ids or (unique_artists and ids & used):
            continue
        picked.append(c)
        used |= ids
        if len(picked) >= count:
            break
    return picked
