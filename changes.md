# Changes

2026.11.06 - Initial release

* `clean`: removes Whisper hallucinations (outros, thanks, TV break filler, subscribe lines) with pattern packs for English, German, Spanish, French, Italian, Portuguese, Dutch, Russian, Japanese, Chinese and Korean
* `clean`: removes fake subtitle and dubbing credits, including fragments split across cues or mixed into real lines
* `clean`: removes sound tags and music notes, including tags split across two cues, without touching the same words in real lines
* `clean`: splits overlong cues at sentence and line breaks, rewraps to two lines (42 characters, 16 for CJK), fixes overlaps, closes small gaps, stretches flash cues
* `clean`: optional collapse of repeated words and repeated cues
* `clean`: batch mode, dry run, in-place with backup, output directory, format conversion, Windows-1252 fallback for non-UTF-8 files
* `clean`: user patterns file at ~/.config/subscrub/patterns.conf
* `transcribe`: ffmpeg plus whisper.cpp from a media file to cleaned subtitles, with optional VAD
* `redo`: re-transcribes a time range in a forced language and splices it in
* `patterns`: lists every built-in rule
* Leaves the markup alone on cues it doesn't change, so styled ASS files keep their styling
* Test suite and a GitHub Actions workflow that runs it on every push

Reasons for changes: Grew out of a one-off script for cleaning a Whisper transcript of a mixed English and German live concert. The same junk shows up in every Whisper transcript, so it became a general tool.
