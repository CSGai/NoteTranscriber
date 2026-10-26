"""Pure pixel math and press/release bookkeeping. Nothing here touches the screen."""

from __future__ import annotations

import statistics
from collections.abc import Sequence

import numpy

from src.keys import MIDDLE_C, NOTE_NAMES_IN_OCTAVE, is_black, midi_number, note_name

STRETCH_PERCENTILES = (1, 99)  # the scan line is stretched so these brightness percentiles become 0 and 255
FULL_SCALE = 255.0
BLACK_KEY_THRESHOLDS = (100, 80, 120, 60, 140)  # darkness cutoffs for black keys, tried in this order
MIN_BLACK_KEY_WIDTH_FRACTION = 0.005  # dark runs narrower than this fraction of the row are gap lines, not keys
MIN_RUN_FRACTION = 0.4  # and runs narrower than this fraction of the median remaining run are frame lines
MIN_BLACK_KEYS = 5  # one octave's worth; fewer cannot show where the groups of two and three fall
GAMMA_SWEEP = range(0, 20)  # gamma values tried, in order, until the white blobs interleave with the black keys
BINARY_THRESHOLDS = (127, 96, 160, 64, 192)  # brightness cutoffs for white-key blobs, tried in this order
BINARY_MAX = 255
SCAN_BAND_HEIGHT = 2  # rows of the screenshot used for the white-key blobs
MIN_KEYS = len(NOTE_NAMES_IN_OCTAVE)  # a full octave of keys pins down which note the keyboard starts on
MIN_KEY_SPACING_FRACTION = 0.1  # neighbouring key centres closer than this fraction of a white key are a bad layout
MAX_KEY_SPACING_FRACTION = 1.2  # and further apart than this are a bad layout
GLOW_FRACTION = (
    0.45  # a key changing less than this fraction of what a neighbour of its colour changed is catching its glow
)
CROSS_GLOW_FRACTION = 0.2  # the same for a neighbour of the other colour, whose change is not comparable
GLOW_REACH = 2  # how many keys to each side a lit key's glow can reach (the next black key over)
MIN_NOTE_SECONDS = 0.04  # a press shorter than this is flicker, not a note


class CalibrationError(RuntimeError):
    """Raised when the keys along the scan line do not look like a piano."""


class NoBlackKeysError(CalibrationError):
    """Raised when a row has no dark runs wide enough to be black keys, so it lies below them."""


def stretch_contrast(image: numpy.ndarray) -> numpy.ndarray:
    """Rescale a grayscale image so its darkest pixels become 0 and its brightest 255.

    This makes the darkness and brightness cutoffs relative, so a dim render (whites around 45,
    blacks around 13) is read the same way as a bright one.
    """
    low, high = numpy.percentile(image, STRETCH_PERCENTILES)
    if high <= low:
        raise CalibrationError("the scan line is a single flat shade; move it so it crosses the keys")
    return numpy.clip((image - low) * (FULL_SCALE / (high - low)), 0, FULL_SCALE).astype(numpy.uint8)


def black_key_positions(gray_row: Sequence[int], start_x: int, threshold: int) -> list[int]:
    """Screen x centres of the black keys along one grayscale row that crosses them, left to right.

    ``gray_row[i]`` is the grayscale value at screen x ``start_x + i``; a pixel at or below
    ``threshold`` is dark. Each run of dark pixels is a candidate; runs touching either end of the
    row, runs far too narrow for a key (gap lines between white keys) and runs much narrower than
    the typical one (frame lines) are dropped.
    """
    runs: list[tuple[int, int]] = []  # (first dark index, last dark index)
    run_start: int | None = None
    for i, value in enumerate(gray_row):
        dark = value <= threshold
        if dark and run_start is None:
            run_start = i
        elif not dark and run_start is not None:
            runs.append((run_start, i - 1))
            run_start = None
    # A run still open at the end touches the right edge, so it is not a key.

    min_width = len(gray_row) * MIN_BLACK_KEY_WIDTH_FRACTION
    runs = [(a, b) for a, b in runs if a > 0 and b - a + 1 >= min_width]
    if not runs:
        return []
    min_width = statistics.median(b - a + 1 for a, b in runs) * MIN_RUN_FRACTION
    return [start_x + (a + b) // 2 for a, b in runs if b - a + 1 >= min_width]


def black_key_pitches(black_xs: Sequence[int]) -> list[str] | None:
    """Pitch names (no octave) of a row of black keys, read off the gaps between them; None if not piano-like.

    Black keys come in groups of two (C# D#) and three (F# G# A#) with a wider gap between the
    groups, so the pattern of wide gaps says which black key the row starts on.
    """
    if len(black_xs) < MIN_BLACK_KEYS:
        return None
    gaps = [b - a for a, b in zip(black_xs, black_xs[1:], strict=False)]
    wide_cutoff = (min(gaps) + max(gaps)) / 2
    wide = [gap > wide_cutoff for gap in gaps]

    pitches = [name for name in NOTE_NAMES_IN_OCTAVE if is_black(name)]
    for start in range(len(pitches)):
        names = [pitches[(start + i) % len(pitches)] for i in range(len(black_xs))]
        steps = [(midi_number(b + "0") - midi_number(a + "0")) % 12 for a, b in zip(names, names[1:], strict=False)]
        if [step == 3 for step in steps] == wide:  # D# to F# and A# to C# skip two white keys
            return names
    return None


def find_black_key_centres(gray_row: Sequence[int], start_x: int) -> list[int]:
    """Screen x centres of the black keys, trying each darkness cutoff until the row looks like a piano.

    Raises NoBlackKeysError if no cutoff finds any key-sized dark run, else CalibrationError if the
    runs never group like a piano's black keys.
    """
    any_runs = False
    for threshold in BLACK_KEY_THRESHOLDS:
        centres = black_key_positions(gray_row, start_x, threshold)
        any_runs = any_runs or bool(centres)
        if black_key_pitches(centres) is not None:
            return centres
    if not any_runs:
        raise NoBlackKeysError("no dark runs wide enough to be black keys")
    raise CalibrationError("the dark runs never fall into a piano's groups of two and three black keys")


def apply_gamma(image: numpy.ndarray, gamma: float) -> numpy.ndarray:
    """Gamma-correct an 8-bit grayscale image."""
    return (numpy.power(image / FULL_SCALE, gamma) * FULL_SCALE).astype(numpy.uint8)


def find_white_key_centres(strip: numpy.ndarray, black_xs: Sequence[int]) -> list[int]:
    """x centres (relative to the strip) of the white keys in a thin grayscale strip along the scan line.

    The strip is thresholded into bright blobs, one per white key between the black keys and the
    lines that separate the whites. The brightness cutoff and gamma are swept until the blobs
    interleave with ``black_xs`` (also relative to the strip) the way piano keys do.
    """
    import cv2  # imported here so the pure functions above stay importable without OpenCV

    for threshold in BINARY_THRESHOLDS:
        for gamma in GAMMA_SWEEP:
            _, binary = cv2.threshold(apply_gamma(strip, gamma), threshold, BINARY_MAX, cv2.THRESH_BINARY)
            contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            centres = []
            for contour in contours:
                m = cv2.moments(contour)
                if m["m00"] != 0:
                    centres.append(int(m["m10"] / m["m00"]))
            try:
                key_layout(black_xs, centres)
            except CalibrationError:
                continue
            return sorted(centres)
    raise CalibrationError("no brightness cutoff or gamma gave white keys that interleave with the black keys")


def piano_pattern(start_pitch_class: int, count: int) -> list[bool]:
    """Which of ``count`` keys are black, starting from a pitch class (0 = C)."""
    return [is_black(NOTE_NAMES_IN_OCTAVE[(start_pitch_class + i) % 12]) for i in range(count)]


def prefix_length(expected: Sequence[bool], actual: Sequence[bool]) -> int:
    """How many leading items the two sequences agree on."""
    return next((i for i, (e, a) in enumerate(zip(expected, actual, strict=True)) if e != a), len(actual))


def key_names(colours: Sequence[bool], lowest_note: str | None = None) -> list[str]:
    """Names of a row of keys, low to high, given which of them are black.

    The row is matched against the piano's colour pattern from each of the 12 possible first notes.
    The octave is the one that puts middle C nearest the middle of the keyboard, as on a real piano,
    unless ``lowest_note`` names the leftmost key outright.
    """
    colours = list(colours)
    if len(colours) < MIN_KEYS:
        raise CalibrationError(
            f"found only {len(colours)} keys, need at least {MIN_KEYS}; re-pick the keyboard corners"
        )

    starts = [start for start in range(12) if piano_pattern(start, len(colours)) == colours]
    if not starts:
        longest = max(prefix_length(piano_pattern(start, len(colours)), colours) for start in range(12))
        raise CalibrationError(
            f"key colours stop following the piano pattern at key {longest + 1} of {len(colours)}; move the scan line"
        )
    pitch_class = starts[0]

    if lowest_note is None:
        candidates = range(pitch_class, 128 - len(colours), 12)
        lowest = min(candidates, key=lambda low: (abs(low + (len(colours) - 1) / 2 - MIDDLE_C), -low))
    else:
        lowest = midi_number(lowest_note)
        if lowest % 12 != pitch_class:
            raise CalibrationError(f"the leftmost key is a {NOTE_NAMES_IN_OCTAVE[pitch_class]}, not {lowest_note}")
    return [note_name(midi) for midi in range(lowest, lowest + len(colours))]


def key_layout(
    black_xs: Sequence[int], white_xs: Sequence[int], lowest_note: str | None = None
) -> tuple[list[int], list[str]]:
    """Every key's x and name, low to high, from the black and white centres found along the scan line.

    Raises CalibrationError if the colours do not follow the piano pattern or the spacing is uneven.
    """
    tagged = sorted([(x, True) for x in black_xs] + [(x, False) for x in white_xs])
    names = key_names([colour for _, colour in tagged], lowest_note)
    positions = [x for x, _ in tagged]

    whites = sorted(white_xs)
    white_width = statistics.median(b - a for a, b in zip(whites, whites[1:], strict=False))
    low, high = white_width * MIN_KEY_SPACING_FRACTION, white_width * MAX_KEY_SPACING_FRACTION
    for name, a, b in zip(names, positions, positions[1:], strict=False):
        if not low <= b - a <= high:
            raise CalibrationError(
                f"{name} and the next key are {b - a} px apart, expected between {low:.0f} and {high:.0f}; "
                "re-pick the keyboard corners"
            )
    return positions, names


def pressed_keys(changes: Sequence[float], black: Sequence[bool], threshold: float) -> list[bool]:
    """Which keys are down, given how far each key's brightness has moved from its resting value.

    A key counts as pressed when it changed by more than ``threshold`` and by at least
    ``GLOW_FRACTION`` of what any key of its own colour within ``GLOW_REACH`` of it changed, and
    ``CROSS_GLOW_FRACTION`` of what any key of the other colour there changed: a lit key's glow
    spills onto the keys around it, but far less than the lit key itself changes. The fraction is
    looser across colours because a lit black key changes shade two or three times as much as a
    lit white key, which would otherwise make a white key lit beside it look like glow.
    """
    pressed = []
    for i, (change, colour) in enumerate(zip(changes, black, strict=True)):
        window = range(max(0, i - GLOW_REACH), min(len(changes), i + GLOW_REACH + 1))
        peak = max(changes[j] for j in window if black[j] == colour)
        other_peak = max((changes[j] for j in window if black[j] != colour), default=0.0)
        pressed.append(
            change > threshold and change >= GLOW_FRACTION * peak and change >= CROSS_GLOW_FRACTION * other_peak
        )
    return pressed


class KeyState:
    """Press/release bookkeeping for every key.

    A key is "down" while ``pressed_at[i]`` holds the time it went down, else it is up.
    """

    def __init__(self, names: Sequence[str], started_at: float = 0.0) -> None:
        self.names = tuple(names)
        self.started_at = started_at
        self.pressed_at: list[float | None] = [None] * len(self.names)

    def update(self, pressed: Sequence[bool], spiked: Sequence[bool], now: float) -> list[tuple[str, float, float]]:
        """Apply one frame of press flags and return the notes that finished this frame.

        A key goes down when it is first pressed and comes up when it stops being pressed. A key
        that is already down and has ``spiked`` (its brightness jumped again this frame) has been
        hit again, so its note ends and a new one starts: a quick repeat of the same note does not
        need the key to return to its resting shade in between. A press shorter than
        ``MIN_NOTE_SECONDS`` is flicker, from a neighbour's glow fading or video noise, and is dropped.

        Each note is ``(key name, start seconds since the session began, seconds held)``.
        """
        finished: list[tuple[str, float, float]] = []
        for i, (is_pressed, did_spike) in enumerate(zip(pressed, spiked, strict=True)):
            down_since = self.pressed_at[i]
            if is_pressed and down_since is not None and not did_spike:
                continue
            if down_since is not None and now - down_since >= MIN_NOTE_SECONDS:
                finished.append((self.names[i], down_since - self.started_at, now - down_since))
            self.pressed_at[i] = now if is_pressed else None
        return finished

    def active_names(self) -> list[str]:
        """Names of the keys currently down, lowest to highest."""
        return [name for name, since in zip(self.names, self.pressed_at, strict=True) if since is not None]
