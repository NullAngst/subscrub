# Maintenance

Check this every couple of months. About fifteen minutes.

## 1. Run the tests against current dependencies

1. In your clone: `python3 -m venv .venv` if you don't have one yet.
2. `.venv/bin/pip install --upgrade pysubs2 pytest`
3. `.venv/bin/python -m pytest -q`

GitHub Actions runs the same thing on every push, on the oldest supported Python and the newest. If the Actions tab shows a failure you didn't cause, a new pysubs2 or Python release is the likely reason. Check the [pysubs2 releases](https://github.com/tkarabela/pysubs2/releases) first.

## 2. Check whisper.cpp still takes the same flags

`transcribe` and `redo` call `whisper-cli` with `-m`, `-l`, `-mc`, `-osrt`, `-of`, `-f`, and with a VAD model `--vad` and `--vad-model`.

1. Update your whisper.cpp: `git pull`, then rebuild with `cmake --build build -j --config Release`, since this is the binary you'll test with.
2. Run `build/bin/whisper-cli --help` and check those flags are still listed.
3. If one got renamed, fix it in `run_whisper()` in `subscrub.py`.
4. Run a quick `subscrub transcribe` on a short clip to make sure it still produces an SRT.

## 3. Look for new hallucinations

New Whisper models and new fine-tunes invent new lines.

1. Skim the whisper.cpp and openai/whisper issue trackers for "hallucination". Lines people report over and over are worth adding.
2. Check this repo's own issues for reports of lines Subscrub missed.
3. Add them to the right language in `BUILTIN` in `subscrub.py`: `D(...)` if the whole cue is junk, `C(...)` if it's a phrase inside real cues. Add a test for each to `tests/test_subscrub.py`, in `test_drops_outros` or `test_drops_credits`.
4. Make sure a real sentence with the same words survives. Every pattern should have an anchor (a whole-cue match, a name, a broadcaster, a year) so it doesn't eat ordinary speech.

## 4. Check the README links

The README links to whisper.cpp, Subtitle Edit, Buzz, whisper-ctranslate2, WhisperX and two Hugging Face model pages. Click through them. Projects move, especially between GitHub orgs.

## 5. Release

1. Bump `__version__` in `subscrub.py` and `version` in `pyproject.toml`, keep them the same.
2. Add an entry to `changes.md`.
3. Push. Users get it with `pipx upgrade subscrub`.
