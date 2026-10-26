"""Command-line entry: flags, prompts and wiring the pieces together."""

from __future__ import annotations

import argparse

from src.midi import MidiWriter
from src.screen import (
    MSS_MONITOR_INDEX,
    PREVIEW_MONITOR_INDEX,
    SCREENINFO_MONITOR_INDEX,
    MousePointPicker,
    ScreenGrabber,
    get_monitor_size,
    show_calibration_preview,
    stop_requested,
)
from src.transcriber import PRESS_THRESHOLD, Transcriber

PROMPT_SONG_NAME = "input song name:"
PROMPT_TEMPO = "\ninput song tempo (leave blank to detect it from the song):"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record a Synthesia-style on-screen piano to a MIDI file.")
    parser.add_argument("-n", "--name", help="song name (used for the .mid file); prompted if omitted")
    parser.add_argument("-t", "--tempo", type=int, help="song tempo in BPM; prompted if omitted, detected if blank")
    parser.add_argument(
        "--threshold", type=int, default=PRESS_THRESHOLD, help="grayscale change that counts as a key press"
    )
    parser.add_argument("--lowest-note", help="name of the leftmost key (such as A0) if the octave is guessed wrong")
    parser.add_argument("--monitor", type=int, default=MSS_MONITOR_INDEX, help="mss monitor index to capture")
    parser.add_argument(
        "--preview-monitor",
        type=int,
        default=PREVIEW_MONITOR_INDEX,
        help="screeninfo monitor index for the preview window",
    )
    return parser.parse_args()


def prompt_song_and_tempo(name: str | None, tempo: int | None) -> tuple[str, int | None]:
    """Ask for whatever was not given on the command line. A blank tempo means "detect it"."""
    if name is None:
        print(PROMPT_SONG_NAME)
        name = input()
    if tempo is None:
        print(PROMPT_TEMPO)
        answer = input().strip()
        tempo = int(answer) if answer else None
    return name, tempo


def main() -> None:
    args = parse_args()
    name, tempo = prompt_song_and_tempo(args.name, args.tempo)

    midi = MidiWriter(f"{name}.mid", tempo)
    width, height = get_monitor_size(SCREENINFO_MONITOR_INDEX)
    screen = ScreenGrabber(0, 0, width, height, args.monitor)

    transcriber = Transcriber(
        screen, midi, MousePointPicker().wait_for_point, threshold=args.threshold, lowest_note=args.lowest_note
    )
    transcriber.calibrate()
    show_calibration_preview(
        transcriber.keyboard_image(),
        transcriber.black_key_xs,
        transcriber.white_key_xs,
        transcriber.region.width,
        transcriber.region.height,
        args.preview_monitor,
    )
    transcriber.run(stop_requested)
