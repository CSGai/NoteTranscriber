"""Note names and MIDI numbers."""

NOTE_NAMES_IN_OCTAVE = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
MIDDLE_C = 60


def note_name(midi: int) -> str:
    """Scientific pitch name for a MIDI note number (60 -> "C4")."""
    return f"{NOTE_NAMES_IN_OCTAVE[midi % 12]}{midi // 12 - 1}"


def midi_number(name: str) -> int:
    """MIDI note number for a scientific pitch name ("C4" -> 60)."""
    pitch = name.rstrip("-0123456789")
    return NOTE_NAMES_IN_OCTAVE.index(pitch) + (int(name[len(pitch) :]) + 1) * 12


def is_black(name: str) -> bool:
    return "#" in name
