# Subscrub

Subscrub cleans up machine-generated subtitles, mostly from Whisper, for anyone who has run speech-to-text on a video and got back a file full of junk.

Whisper is good at transcribing. It is also very sure of itself over silence, music and crowd noise, and that's where it makes things up. Subscrub finds the made-up lines and removes them, then fixes the layout and timing problems Whisper leaves behind. It works on any subtitle file, whichever tool made it.

## What it fixes

* **Invented outros and filler.** "Thank you.", "I'll see you next time.", "We'll be right back", "Please like and subscribe", and the same lines in German, Spanish, French, Italian, Portuguese, Dutch, Russian, Japanese, Chinese and Korean. Whisper learned these from YouTube and TV captions and drops them into any quiet stretch.
* **Fake subtitle credits.** "Untertitel im Auftrag des ZDF, 2020", "Subtitles by the Amara.org community", German dubbing credits like "Sprecher Jochen Graf", and so on. Including the pieces Whisper splits them into, like "für funk" on its own or tacked onto a real line.
* **Sound tags and music notes.** `[Music]`, `(applause)`, `* Musik *`, `* Jubel und Applaus *`, stray ♪. Also the ones Whisper splits over two cues, with `*` in one and `Musik *` in the next. A word like "Musik" is only removed next to a tag marker, so a real line that says "die Musik" keeps it.
* **Overlong cues.** Splits cues with too much text, or that stay on screen too long, at a real break: end of a sentence, a comma, or where a new line of speech or lyrics starts. Time is shared out by character count.
* **Bad wrapping.** Rewraps to two lines of 42 characters, or 16 for Chinese, Japanese and Korean. Cues that are already wrapped fine are left alone.
* **Bad timing.** Fixes overlaps, closes gaps under 0.8 seconds so lines don't blink off and on, stretches flash cues to 1.2 seconds where there's room.
* **Loops, if you ask.** Whisper sometimes gets stuck repeating one word or one line. `--max-word-repeat` and `--max-repeats` handle that. They're off by default, since songs repeat on purpose.

Every change is printed with its timestamp, so you can check what it did. Your original file is never touched unless you pass `--in-place`, which keeps a `.bak` copy anyway.

It reads and writes SRT, WebVTT, ASS/SSA, MicroDVD and the other formats [pysubs2](https://github.com/tkarabela/pysubs2) handles, and it can convert between them.

## Prerequisites

* Python 3.10 or newer
* pipx, to install it without touching your system Python
* For `transcribe` and `redo` only: ffmpeg, whisper.cpp and a Whisper model (see [Getting Whisper](#getting-whisper))

## Install

1. Install pipx. I use apt, so in my case that's `sudo apt install pipx`. It depends on your system: `dnf install pipx`, `pacman -S python-pipx`, `brew install pipx`, or whichever.
2. Make sure pipx's bin folder is on your PATH: `pipx ensurepath`, then open a new terminal.
3. Install Subscrub: `pipx install git+https://github.com/NullAngst/Subscrub`
4. Check it: `subscrub --version`

To update later: `pipx upgrade subscrub`.

No pipx? Clone the repo, make a venv with `python3 -m venv .venv`, run `.venv/bin/pip install .`, and use `.venv/bin/subscrub`.

## Usage

### Clean a file

```
subscrub clean movie.srt
```

That writes `movie.clean.srt` next to it and prints what it changed. Some useful variations:

```
subscrub clean -n movie.srt                  # dry run: show what would change, write nothing
subscrub clean *.srt --out-dir cleaned       # a whole folder at once
subscrub clean movie.srt --format vtt        # clean and convert to WebVTT
subscrub clean movie.srt --keep-thanks       # someone on screen really does say "thank you"
subscrub clean movie.srt --lang-packs en,de  # only the English and German pattern packs
```

### Make subtitles from a video

```
subscrub transcribe concert.mkv --model ~/models/ggml-large-v3.bin
```

That pulls the audio out with ffmpeg, runs whisper.cpp on it, cleans the result, and writes `concert.srt`. It always passes `-mc 0` to whisper.cpp, which stops earlier text from being fed into later chunks. That's the main reason Whisper gets stuck in one language or keeps repeating a phrase.

Language is auto-detected unless you set it: `-l de`.

### Re-do part of a file

If one stretch came out wrong, re-transcribe just that range and splice it in:

```
subscrub redo concert.clean.srt concert.mkv 17:26 18:15 de --model ~/models/ggml-large-v3.bin
```

Times can be `17:26`, `1:01:03`, `1:01:03.5`, or plain seconds. Cues whose middle falls in the range get replaced.

To skip typing paths every time, set these in your `~/.bashrc` (or whichever shell rc you use):

```
export SUBSCRUB_MODEL=~/models/ggml-large-v3.bin
export SUBSCRUB_WHISPER=~/whisper.cpp/build/bin/whisper-cli   # only if it's not on your PATH
export SUBSCRUB_VAD_MODEL=~/models/ggml-silero-v5.1.2.bin     # optional, see below
```

### Mixed-language videos

Whisper picks a language near the start and tends to stick with it. In a video that switches between two languages, it will often translate the second one into the first instead of transcribing it. Whether the output came out translated is easy to spot: the wrong language shows up in the middle of a scene or song.

The fix is `redo` on each stretch with the language forced. Transcribe once on auto, find the stretches that came out wrong, and redo each with `-l` set to what is actually spoken.

### Add your own patterns

New Whisper versions invent new lines. Put your own rules in `~/.config/subscrub/patterns.conf`, one per line:

```
drop that's all for today\.?
cut \bsome channel name\b,?
```

`drop` deletes a cue whose whole text matches. `cut` removes the match from anywhere in a cue. Both are case-insensitive; `drop-case` and `cut-case` aren't. See `patterns.example.conf`. Run `subscrub patterns` to see every built-in rule and where your file goes.

## Getting Whisper

You only need this to make subtitles. If you already have a subtitle file, skip to [Usage](#usage).

### The easy way: a GUI

* **[Subtitle Edit](https://github.com/SubtitleEdit/subtitleedit)**, for Windows, macOS and Linux. Open a video, go to Video → Speech to text, pick an engine and model, and it downloads everything itself. Its built-in editor is also the best place to fix whatever Subscrub can't.
* **[Buzz](https://github.com/chidiwilliams/buzz)**, for Windows, macOS and Linux (Flathub). Simpler, and exports SRT and VTT.

Then run `subscrub clean` on what they export.

### The command line: whisper.cpp

`subscrub transcribe` and `subscrub redo` use [whisper.cpp](https://github.com/ggml-org/whisper.cpp). It runs on CPU, or on your GPU through Vulkan (AMD, Intel and NVIDIA) or CUDA (NVIDIA).

Some package managers have it, `brew install whisper-cpp` for one, but names and versions vary between distros, and distro builds are often CPU-only. Building it is quick:

1. Install a compiler, cmake and git. I use apt, so in my case `sudo apt install build-essential cmake git`. It depends on your system.
2. For Vulkan, also install the Vulkan headers and shader compiler. On apt that's `libvulkan-dev glslc`, package names vary elsewhere.
3. `git clone https://github.com/ggml-org/whisper.cpp`
4. `cd whisper.cpp`
5. Configure it. Pick one:
   * CPU only: `cmake -B build`
   * Vulkan: `cmake -B build -DGGML_VULKAN=1`
   * NVIDIA CUDA: `cmake -B build -DGGML_CUDA=1`, needs the CUDA toolkit installed
6. `cmake --build build -j --config Release`
7. The program is now at `build/bin/whisper-cli`. Point `SUBSCRUB_WHISPER` at it, or copy it somewhere on your PATH.

If you used Subtitle Edit's whisper.cpp engine, it already downloaded a `whisper-cli` and models. Find them with `find ~ -name whisper-cli -type f` and `find ~ -name 'ggml-*.bin'`.

### Models

From inside the whisper.cpp folder: `sh ./models/download-ggml-model.sh large-v3`. That saves `models/ggml-large-v3.bin`. They also download straight from [ggerganov/whisper.cpp on Hugging Face](https://huggingface.co/ggerganov/whisper.cpp/tree/main).

Which one:

* **large-v3**, about 3 GB. The best, especially for anything other than English. Use this unless it's too slow.
* **large-v3-turbo**, about 1.6 GB. Much faster, a little weaker outside English.
* **Quantized versions** (`-q5_0` and so on) are a third the size with a small accuracy hit. Use them if you run out of VRAM.
* **medium** and smaller. Fine for clear speech, noticeably worse at music and language switching.
* **Anything ending in `.en`** is English-only. DO NOT USE AN `.en` MODEL ON ANYTHING WITH ANOTHER LANGUAGE IN IT. It will mangle or skip every non-English line.

### VAD (optional)

Voice activity detection skips non-speech before Whisper sees it, which stops most hallucinations from happening in the first place. Get the Silero model with `sh ./models/download-vad-model.sh silero-v5.1.2` from the whisper.cpp folder, or from [ggml-org/whisper-vad on Hugging Face](https://huggingface.co/ggml-org/whisper-vad/tree/main), and pass it with `--vad-model` or `SUBSCRUB_VAD_MODEL`.

One catch: VAD is tuned for speech, so on music it can also skip vocals buried under loud instruments. Try it on one song before running a whole concert with it.

### Other Whisper tools

faster-whisper, [whisper-ctranslate2](https://github.com/Softcatala/whisper-ctranslate2) and [WhisperX](https://github.com/m-bain/whisperX) all produce SRT files `subscrub clean` handles fine. `transcribe` and `redo` only drive whisper.cpp.

## Options

`subscrub clean --help` lists all of them. The ones you'll reach for:

| Option | Default | What it does |
|---|---|---|
| `-o FILE` | `NAME.clean.EXT` | Output path, one input only |
| `--out-dir DIR` | next to input | Where outputs go |
| `--in-place` | off | Overwrite the input, keeping a `.bak` |
| `--format FMT` | same as input | Output format: srt, vtt, ass, ssa, microdvd, json |
| `-n`, `--dry-run` | off | Report only, write nothing |
| `--lang-packs LIST` | all | Pattern packs: en, de, es, fr, it, pt, nl, ru, ja, zh, ko |
| `--patterns FILE` | none | Extra patterns file, repeatable |
| `--keep-thanks` | off | Keep lone "Thank you." style cues |
| `--keep-sound-tags` | off | Keep `[Music]` and friends |
| `--strip-all-tags` | off | Remove every short `[..]`, `(..)` or `*..*` tag, like `[door slams]` |
| `--max-word-repeat N` | off | Cut a word or phrase repeated more than N times in a row |
| `--max-repeats N` | off | Drop a cue repeated more than N times in a row |
| `--max-chars N` | 42 | Characters per line |
| `--max-chars-cjk N` | 16 | Characters per line for Chinese, Japanese, Korean |
| `--max-dur MS` | 7000 | Split cues on screen longer than this, if there's a real break |
| `--min-dur MS` | 1200 | Stretch cues shorter than this |
| `--close-gap MS` | 800 | Close gaps up to this size |
| `--no-split` | off | Never split cues |
| `--no-timing` | off | Leave gaps and short cues alone |

## Limits

* It can't hear the audio. It can't tell a translated line from a transcribed one, and it can't add words Whisper missed. `redo` is for that.
* Long cues with no punctuation and no clear line start stay long, since splitting anywhere else would cut mid-phrase.
* Dropping "Thank you." is right almost every time Whisper writes it alone over music. It's wrong when someone on screen actually says it. The report shows every one it dropped, and `--keep-thanks` turns that off.
* The line-break guess for German looks for words like "Und", "Doch", "Wenn" and "Ich" capitalized mid-text, since German capitalizes every noun. Right most of the time, not always.
* Styled ASS files keep their styling on every cue Subscrub doesn't change. A cue it does change, splits or rewraps loses its inline tags.
* The pattern packs for languages other than English and German are built from known Whisper hallucinations, not long testing. If you hit a junk line it missed, add it to your patterns file, and open an issue so it can go in the built-in list.

## License

GPL-3.0-or-later.

Now you've got subtitles with the invented lines gone, the long cues split at sensible spots, and timing that doesn't flicker. Tinker with the options and the patterns file as you see fit.
