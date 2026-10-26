"""Single-track MIDI output over midiutil."""

from __future__ import annotations

import os

from midiutil.MidiFile import MIDIFile

from src.keys import midi_number
from src.tempo import estimate_tempo

TRACK = 0
START_TIME = 0
TRACK_NAME = "Sample Track"
CHANNEL = 0
VOLUME = 70
SUSTAIN_CONTROLLER = 64
SUSTAIN_OFF = 0
SUSTAIN_ON = 127
SECONDS_PER_MINUTE = 60


class MidiWriter:
    """Collects notes (in seconds) and writes them as one MIDI track at the song's tempo.

    Every note is wrapped in a sustain-pedal off / note / sustain-pedal on triple at the
    note's start. If no tempo is given it is guessed from the note onsets when the file is written.
    """

    def __init__(self, path: str | os.PathLike[str], tempo: int | None = None) -> None:
        self.path = path
        self.tempo = tempo
        self.notes: list[tuple[str, float, float]] = []

    def add_note(self, key: str, start: float, duration: float) -> None:
        """Queue one note by key name (``"C4"``); start and duration are in seconds."""
        self.notes.append((key, start, duration))

    def write(self) -> None:
        """Write the queued notes to ``self.path``."""
        tempo = self.tempo or estimate_tempo([start for _, start, _ in self.notes])
        print(f"finished song, {len(self.notes)} notes at {tempo} BPM")

        midi_file = MIDIFile(1)
        midi_file.addTrackName(TRACK, START_TIME, TRACK_NAME)
        midi_file.addTempo(TRACK, START_TIME, tempo)
        beats_per_second = tempo / SECONDS_PER_MINUTE
        for key, start, duration in self.notes:
            time = start * beats_per_second
            midi_file.addControllerEvent(TRACK, CHANNEL, time, SUSTAIN_CONTROLLER, SUSTAIN_OFF)
            midi_file.addNote(TRACK, CHANNEL, midi_number(key), time, duration * beats_per_second, VOLUME)
            midi_file.addControllerEvent(TRACK, CHANNEL, time, SUSTAIN_CONTROLLER, SUSTAIN_ON)

        with open(self.path, "wb") as out:
            midi_file.writeFile(out)
