"""Guess a song's tempo from its note onsets, for recordings whose notes sit on a grid (MIDI playback)."""

from __future__ import annotations

import statistics

DEFAULT_TEMPO = 120  # used when there are too few notes, or they do not fit a grid
MIN_GAPS = 8  # fewer onset gaps than this and the guess is not worth making
CHORD_SPREAD = 0.04  # seconds; onsets closer than this are one chord, not a gap
CLUSTER_WIDTH = 0.025  # seconds; capture jitter allowance when looking for the most common gap
GRID_TOLERANCE = 0.2  # a gap is "on the grid" if it is within this fraction of a whole number of units
MIN_GRID_FIT = 0.8  # fraction of gaps that must sit on the grid to trust it
SUBDIVISIONS = (1, 2, 3, 4)  # try the common gap, then halves, triplets and quarters of it as the grid unit
BEAT_MULTIPLES = (4, 8, 2, 16, 1, 32, 3, 6, 12, 24)  # grid units per beat, most likely first
TEMPO_LOW = 80  # inclusive
TEMPO_HIGH = 160  # exclusive, so exactly one doubling of a beat falls in range


def estimate_tempo(onsets: list[float]) -> int:
    """Tempo in BPM that best explains when the notes started, or DEFAULT_TEMPO if none does.

    Finds the most common gap between successive onsets, takes it (or a simple subdivision of it)
    as the grid unit, then picks the multiple of that unit whose BPM lands in [TEMPO_LOW, TEMPO_HIGH).
    """
    starts = sorted(onsets)
    gaps = [b - a for a, b in zip(starts, starts[1:], strict=False) if b - a > CHORD_SPREAD]
    if len(gaps) < MIN_GAPS:
        print(f"not enough notes to guess a tempo, using {DEFAULT_TEMPO} BPM")
        return DEFAULT_TEMPO

    common = _most_common_gap(gaps)
    for divisor in SUBDIVISIONS:
        unit = common / divisor
        if _grid_fit(gaps, unit) >= MIN_GRID_FIT:
            break
    else:
        print(f"notes do not sit on a steady grid, using {DEFAULT_TEMPO} BPM")
        return DEFAULT_TEMPO

    for multiple in BEAT_MULTIPLES:
        tempo = 60 / (unit * multiple)
        if TEMPO_LOW <= tempo < TEMPO_HIGH:
            return round(tempo)
    return DEFAULT_TEMPO


def _most_common_gap(gaps: list[float]) -> float:
    """Median of the densest cluster of gaps, CLUSTER_WIDTH either side."""
    best: list[float] = []
    for centre in gaps:
        cluster = [g for g in gaps if abs(g - centre) <= CLUSTER_WIDTH]
        if len(cluster) > len(best) or (len(cluster) == len(best) and centre < min(best)):
            best = cluster
    return statistics.median(best)


def _grid_fit(gaps: list[float], unit: float) -> float:
    """Fraction of gaps that are close to a whole number of units."""
    on_grid = sum(1 for g in gaps if abs(g / unit - round(g / unit)) <= GRID_TOLERANCE)
    return on_grid / len(gaps)
