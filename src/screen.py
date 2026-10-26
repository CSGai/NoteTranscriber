"""Everything that touches the desktop: screen capture, mouse/keyboard input and the preview window."""

from __future__ import annotations

import cv2
import keyboard as keyboard_poll
import mss
import numpy
import screeninfo
from pynput import keyboard, mouse

# Monitor indices. screeninfo and mss number monitors differently (mss index 0 is "all monitors").
SCREENINFO_MONITOR_INDEX = 0  # which monitor's size to use for the full-screen grab
MSS_MONITOR_INDEX = 1  # which monitor mss captures
PREVIEW_MONITOR_INDEX = 2  # which monitor the calibration preview window opens on

GRAB_PIXEL_MAX_X = 2559  # grab_pixel clamps x to this
SCAN_ROW_HEIGHT = 1

CORNER_PICK_KEY = keyboard.Key.ctrl_r  # press to confirm a mouse pick
STOP_KEY = "right ctrl"  # hold to stop recording

WINDOW_NAME = "Display"
PREVIEW_WINDOW_OFFSET = (200, 200)
PREVIEW_SCALE_PERCENT = 80
BLACK_LINE_COLOUR = (200, 200, 200)
WHITE_LINE_COLOUR = (50, 100, 255)
LINE_THICKNESS = 1
BLACK_DOT_COLOUR = (200, 60, 255)
WHITE_DOT_COLOUR = (50, 100, 255)
DOT_Y = 100
DOT_RADIUS = 1
DOT_THICKNESS = -1


def get_monitor_size(index: int = SCREENINFO_MONITOR_INDEX) -> tuple[int, int]:
    """``(width, height)`` of the given screeninfo monitor."""
    monitor = screeninfo.get_monitors()[index]
    return monitor.width, monitor.height


class ScreenGrabber:
    """Grabs a rectangle of one monitor as a grayscale numpy image."""

    def __init__(self, left: int, top: int, width: int, height: int, monitor_index: int = MSS_MONITOR_INDEX) -> None:
        self.left = left
        self.top = top
        self.width = width
        self.height = height
        self.monitor_index = monitor_index
        self.sct = mss.mss()
        base = self.sct.monitors[monitor_index]
        self.monitor = {
            "top": base["top"] + top,
            "left": base["left"] + left,
            "width": width,
            "height": height,
            "mon": monitor_index,
        }
        self.screenshot: numpy.ndarray | None = None

    def grab(self, grayscale: bool = True) -> numpy.ndarray:
        """Take a fresh screenshot of the rectangle and keep it on ``self.screenshot``."""
        image = numpy.array(self.sct.grab(self.monitor))
        if grayscale:
            image = cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
        self.screenshot = image
        return image

    def grab_pixel(self, x: int, y: int) -> int:
        """Value of one pixel in the last screenshot; x is clamped to GRAB_PIXEL_MAX_X."""
        if x > GRAB_PIXEL_MAX_X:
            x = GRAB_PIXEL_MAX_X
        return self.screenshot[y][x]

    def grab_window(self, x: int, y: int, half_width: int) -> float:
        """Mean value of the pixels from ``x - half_width`` to ``x + half_width`` on row ``y``."""
        x = min(x, self.screenshot.shape[1] - 1)
        return float(self.screenshot[y, max(0, x - half_width) : x + half_width + 1].mean())

    def segment(self, left: int, top: int, right: int, bottom: int) -> numpy.ndarray:
        """Crop of the last screenshot."""
        return self.screenshot[top:bottom, left:right]

    def row_grabber(self, y: int) -> ScreenGrabber:
        """A grabber covering just the one-pixel-high row at ``y``, for the fast capture loop."""
        return ScreenGrabber(0, y, self.width, SCAN_ROW_HEIGHT, self.monitor_index)


class MousePointPicker:
    """Blocks until the user presses Right-Ctrl, then returns where the mouse was."""

    def __init__(self) -> None:
        self.mouse_coords: tuple[int, int] = (0, 0)
        self.mouse_listener: mouse.Listener | None = None
        self.key_listener: keyboard.Listener | None = None

    def wait_for_point(self) -> tuple[int, int]:
        self.mouse_listener = mouse.Listener(on_move=self._on_move)
        self.key_listener = keyboard.Listener(on_press=self._on_press)
        self.mouse_listener.start()
        self.key_listener.start()
        self.key_listener.join()
        return self.mouse_coords

    def _on_press(self, key: keyboard.Key | keyboard.KeyCode | None) -> None:
        if key == CORNER_PICK_KEY:
            self.mouse_listener.stop()
            self.key_listener.stop()

    def _on_move(self, x: int, y: int) -> None:
        self.mouse_coords = (abs(x), abs(y))


def stop_requested() -> bool:
    """True while the stop key is held."""
    return keyboard_poll.is_pressed(STOP_KEY)


def open_preview_window(
    monitor_index: int = PREVIEW_MONITOR_INDEX, offset: tuple[int, int] = PREVIEW_WINDOW_OFFSET
) -> None:
    monitors = screeninfo.get_monitors()
    if monitor_index >= len(monitors):
        print(f"no monitor {monitor_index} for the preview, using monitor {len(monitors) - 1}")
        monitor_index = len(monitors) - 1
    monitor = monitors[monitor_index]
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    cv2.moveWindow(WINDOW_NAME, monitor.x + offset[0], monitor.y + offset[1])


def draw_key_lines(image: numpy.ndarray, black_xs: list[int], white_xs: list[int]) -> None:
    """Mark every detected key on the keyboard image, in place."""
    height = image.shape[0]
    for x in black_xs:
        cv2.line(image, (x, 0), (x, height), BLACK_LINE_COLOUR, LINE_THICKNESS)
    for x in white_xs:
        cv2.line(image, (x, 0), (x, height), WHITE_LINE_COLOUR, LINE_THICKNESS)
    for x in black_xs:
        cv2.circle(image, (x, DOT_Y), DOT_RADIUS, BLACK_DOT_COLOUR, DOT_THICKNESS)
    for x in white_xs:
        cv2.circle(image, (x, DOT_Y), DOT_RADIUS, WHITE_DOT_COLOUR, DOT_THICKNESS)


def show_image(image: numpy.ndarray, width: int, height: int, scale: int = PREVIEW_SCALE_PERCENT) -> None:
    cv2.resizeWindow(WINDOW_NAME, int(width * scale / 100), int(height * scale / 100))
    cv2.imshow(WINDOW_NAME, image)
    cv2.waitKey(1)


def show_calibration_preview(
    image: numpy.ndarray,
    black_xs: list[int],
    white_xs: list[int],
    width: int,
    height: int,
    monitor_index: int = PREVIEW_MONITOR_INDEX,
) -> None:
    """Show the keyboard crop with the detected keys drawn on it and wait for any key press."""
    open_preview_window(monitor_index)
    draw_key_lines(image, black_xs, white_xs)
    show_image(image, width, height)
    cv2.waitKey(0)
