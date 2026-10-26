# NoteTranscriber

![Python 3.10+](https://img.shields.io/badge/Python%203.10%2B-3776AB?style=flat&logo=python&logoColor=white)
![OpenCV](https://img.shields.io/badge/OpenCV-5C3EE8?style=flat&logo=opencv&logoColor=white)
![License MIT](https://img.shields.io/badge/License-MIT-green?style=flat)

Records a Synthesia-style on-screen piano to a MIDI file.

> Takes notes wink wink

Point it at the on-screen keyboard of a MIDI player, such as Synthesia or a YouTube recording of one, and it writes what gets played to a `.mid` file. It watches one row of pixels across the keys: a key that changes shade is a press, and when it returns to its resting shade the note ends.

## 🔨 Build

Python 3.10 or newer, then:

```sh
pip install -r requirements.txt
```

## 🚀 Usage

Put the piano on screen, paused on a frame with no keys lit, then run:

```sh
python main.py
```

1. Enter a song name and tempo, or pass `-n NAME -t TEMPO`. Leave the tempo blank and it is guessed from the note timing once the song is done.
2. Hover the **top-left** corner of the keyboard and press **Right Ctrl**, then the **bottom-right** corner and **Right Ctrl** again.
3. A preview window shows the keys found. Press any key in it to start recording, then play the video.
4. Hold **Right Ctrl** when the song is over. The file is written next to `main.py` as `NAME.mid`.

### Configuration

| Flag | Default | Meaning |
| --- | --- | --- |
| `-n`, `--name` | prompt | Song name, also the output file name |
| `-t`, `--tempo` | prompt | Tempo in BPM; blank to detect it from the song |
| `--threshold` | 10 | Grayscale change that counts as a key press |
| `--lowest-note` | guessed | Name of the leftmost key, such as `A0`, if the octave is guessed wrong |
| `--monitor` | 1 | mss monitor index to capture |
| `--preview-monitor` | 2 | screeninfo monitor index the preview window opens on |

## 🔍 How it works

- **Finding the keys.** Rows of the keyboard are scanned from just below its top edge. Black keys are the dark runs along a row and white keys the bright blobs between them, and the middle of the rows that read as a piano becomes the scan line.
- **Naming them.** The keyboard does not have to be 88 keys: the groups of black keys say which note each key is, and the octave puts middle C nearest the middle of the keyboard. The range found is printed, for example `96 keys, C0 to B7`.
- **Presses.** A key whose brightness on the scan line moves away from its resting value is pressed, and when it moves back the note ends. Keys that only catch a neighbour's glow, and presses too short to be a note, are ignored. A lit key whose shade jumps again has been hit again, so its note is split there.
- **Output.** The notes go on one MIDI track at the given tempo, or at the tempo guessed from the note onsets.

## 📂 Architecture

```
main.py             entry point
src/cli.py          command-line flags and prompts
src/keys.py         note names and their MIDI numbers
src/screen.py       screen capture, mouse picks, stop key and the preview window
src/detection.py    finding keys along the scan line and tracking presses
src/midi.py         writing the MIDI file
src/tempo.py        guessing the tempo from note onsets
src/transcriber.py  calibration and the capture loop
```

## 🙏 Credits

- Johnathan, big save with the MIDI conversion advice.
- Yahav also helped <3

## 👤 Maintainers

[@CSGai](https://github.com/CSGai)

## 🤝 Contributing

Pull requests are welcome.

## 📄 License

[MIT](LICENSE) © Gai
