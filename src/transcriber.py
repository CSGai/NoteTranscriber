"""Calibration and the capture loop."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy

from src.detection import (
    SCAN_BAND_HEIGHT,
    CalibrationError,
    KeyState,
    NoBlackKeysError,
    find_black_key_centres,
    find_white_key_centres,
    key_layout,
    pressed_keys,
    stretch_contrast,
)
from src.keys import is_black
from src.midi import MidiWriter
from src.screen import ScreenGrabber

PICK_KEY_NAME = "Right Ctrl"
PRESS_THRESHOLD = 10  # grayscale change that counts as a key press; 35 also works on some videos
PROBE_HALF_WIDTH = 2  # each key is sampled as the mean of x-2..x+2 on the scan line
SCAN_START_OFFSET = 25  # the scan line search starts this many px below the keyboard's top edge, under the glow
SEPARATOR = "-" * 100


@dataclass(frozen=True)
class KeyboardRegion:
    """The two user-picked corners, in pick order.

    Not normalised, by design: pick the top-left corner first, then the bottom-right one.
    """

    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return abs(self.left - self.right)

    @property
    def height(self) -> int:
        return abs(self.top - self.bottom)


class Transcriber:
    """Calibrate against the on-screen keyboard, then loop grabbing the scan row and emitting notes."""

    def __init__(
        self,
        screen: ScreenGrabber,
        midi: MidiWriter,
        pick_point: Callable[[], tuple[int, int]],
        threshold: int = PRESS_THRESHOLD,
        lowest_note: str | None = None,
    ) -> None:
        self.screen = screen
        self.midi = midi
        self.pick_point = pick_point
        self.threshold = threshold
        self.lowest_note = lowest_note

        # Set by calibrate().
        self.region: KeyboardRegion | None = None
        self.scan_line_y: int | None = None
        self.black_key_xs: list[int] = []
        self.white_key_xs: list[int] = []
        self.key_xs: list[int] = []
        self.key_names: list[str] = []
        self.key_is_black: list[bool] = []
        self.baseline: list[tuple[int, float]] = []
        self.previous_changes: list[float] = []
        self.row_grabber: ScreenGrabber | None = None
        self.start_time: float = 0.0
        self.key_state: KeyState | None = None

    def calibrate(self) -> None:
        """Pick the keyboard corners, find a scan line that locates every key and record its resting brightness."""
        self.region = self._pick_keyboard_region()
        self.screen.grab()
        self.scan_line_y = self.find_scan_line()
        print(f"scan line y: {self.scan_line_y}")

        print(f"keyboard height {self.region.height}")
        print(f"keyboard width {self.region.width}")
        print(f"{len(self.key_names)} keys, {self.key_names[0]} to {self.key_names[-1]}")
        print(SEPARATOR)
        print(self.key_xs)

        self.key_is_black = [is_black(name) for name in self.key_names]
        self.baseline = [(x, self.screen.grab_window(x, self.scan_line_y, PROBE_HALF_WIDTH)) for x in self.key_xs]

        self.previous_changes = [0.0] * len(self.baseline)
        self.row_grabber = self.screen.row_grabber(self.scan_line_y)
        self.start_time = time.time()
        self.key_state = KeyState(self.key_names, self.start_time)

    def _pick_keyboard_region(self) -> KeyboardRegion:
        """Two corner picks."""
        coordinates: list[int] = []
        for corner in ("top-left", "bottom-right"):
            print(f"point at the {corner} corner of the keyboard, on its edge, then press {PICK_KEY_NAME}")
            x, y = self.pick_point()
            coordinates.append(x)
            coordinates.append(y)
            print(f"{corner} corner: {x}, {y}")
        return KeyboardRegion(*coordinates)

    def find_scan_line(self) -> int:
        """The middle of the rows of the keyboard that give a piano-like layout, storing the keys found on it.

        The search starts SCAN_START_OFFSET below the top edge, where a lit key's glow no longer
        reaches its neighbours, and ends at the first row with no black keys on it. The middle of
        the working rows is clear of both the glow and the ends of the black keys, whatever the
        keyboard's size.
        """
        print("looking for a scan line...")
        working: list[int] = []
        for y in range(self.region.top + SCAN_START_OFFSET, self.region.bottom - SCAN_BAND_HEIGHT):
            try:
                self.key_xs, self.key_names = self.locate_keys(y)
            except NoBlackKeysError:
                break
            except CalibrationError as error:
                print(f"row {y}: {error}")
                continue
            working.append(y)
        if working:
            middle = working[len(working) // 2]
            self.key_xs, self.key_names = self.locate_keys(middle)
            return middle
        raise CalibrationError(
            f"no row from {SCAN_START_OFFSET} px below the keyboard's top edge to the bottom of its black keys "
            "gave a piano-like layout; re-pick the keyboard corners on a frame with no keys lit"
        )

    def locate_keys(self, y: int) -> tuple[list[int], list[str]]:
        """Find the x and name of every key along row ``y`` of the keyboard, low to high.

        The black keys are the dark runs on the row; the white keys are the bright blobs in a thin
        strip along it; the names follow from how the black keys group into twos and threes. Both
        are read after stretching the strip to full contrast, so dim renders work too. Raises
        CalibrationError if the result does not look like a piano.
        """
        strip = stretch_contrast(self.screen.segment(self.region.left, y, self.region.right, y + SCAN_BAND_HEIGHT))
        self.black_key_xs = find_black_key_centres(strip[0], self.region.left)
        relative_black_xs = [x - self.region.left for x in self.black_key_xs]
        self.white_key_xs = [self.region.left + cx for cx in find_white_key_centres(strip, relative_black_xs)]
        return key_layout(self.black_key_xs, self.white_key_xs, self.lowest_note)

    def keyboard_image(self) -> numpy.ndarray:
        """The keyboard crop of the calibration screenshot, for the preview."""
        return self.screen.segment(self.region.left, self.region.top, self.region.right, self.region.bottom)

    def detect_active_keys(self) -> list[str]:
        """Compare the current scan row against the baseline, write finished notes, return the keys now down.

        A key's change is how far its brightness has moved from the baseline; a spike is that
        change growing by more than the threshold since the last frame, which on a key already
        down means it was hit again. One clock read per frame is shared by every key.
        """
        changes = [abs(self.row_grabber.grab_window(x, 0, PROBE_HALF_WIDTH) - value) for x, value in self.baseline]
        pressed = pressed_keys(changes, self.key_is_black, self.threshold)
        spiked = [
            change - before > self.threshold for change, before in zip(changes, self.previous_changes, strict=True)
        ]
        self.previous_changes = changes
        now = time.time()
        for key, start, duration in self.key_state.update(pressed, spiked, now):
            self.midi.add_note(key, start, duration)
        return self.key_state.active_names()

    def run(self, stop_requested: Callable[[], bool]) -> None:
        """Capture frames until ``stop_requested()`` is true, then write the MIDI file."""
        while True:
            self.row_grabber.grab()
            active = self.detect_active_keys()
            print(f"{active}\n")
            if stop_requested():
                self.midi.write()
                break
