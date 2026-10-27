"""Pitch-class key + mode -> Camelot wheel codes and harmonic compatibility."""

# Camelot number for each pitch class (0 = C ... 11 = B); minor = "A", major = "B".
_MAJOR = {0: 8, 1: 3, 2: 10, 3: 5, 4: 12, 5: 7, 6: 2, 7: 9, 8: 4, 9: 11, 10: 6, 11: 1}
_MINOR = {0: 5, 1: 12, 2: 7, 3: 2, 4: 9, 5: 4, 6: 11, 7: 6, 8: 1, 9: 8, 10: 3, 11: 10}
_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def camelot(key: int | None, mode: int | None) -> str | None:
    """key: 0-11 (-1/None unknown); mode: 1 major, 0 minor."""
    if key is None or mode is None or not 0 <= key <= 11:
        return None
    return f"{(_MAJOR if mode == 1 else _MINOR)[key]}{'B' if mode == 1 else 'A'}"


def key_name(key: int | None, mode: int | None) -> str | None:
    if key is None or mode is None or not 0 <= key <= 11:
        return None
    return f"{_NAMES[key]} {'major' if mode == 1 else 'minor'}"


def _parse(code: str) -> tuple[int, str]:
    return int(code[:-1]), code[-1]


def key_distance(a: str | None, b: str | None) -> int | None:
    """Steps on the Camelot wheel: 0 same, 1 = neighbour or relative major/minor, ...
    Returns None if either key is unknown."""
    if not a or not b:
        return None
    (na, la), (nb, lb) = _parse(a), _parse(b)
    ring = min((na - nb) % 12, (nb - na) % 12)
    return ring + (0 if la == lb else 1)


def key_score(a: str | None, b: str | None) -> float:
    """1.0 same key, 0.8 compatible (distance 1), decaying to 0. Unknown -> neutral 0.5."""
    d = key_distance(a, b)
    if d is None:
        return 0.5
    return {0: 1.0, 1: 0.8, 2: 0.4}.get(d, 0.0)
