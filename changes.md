# Changes

2026.11.19 - New German hallucination patterns, # note markers, output errors

* `clean`: drops the German outro "Das war's für heute. Wir sehen uns beim nächsten Mal. Tschüss!" and its pieces, but not a bare "Tschüss!" or "Das war's."
* `clean`: removes "Vertraue und glaube, es hilft, es heilt die göttliche Kraft!" wherever it sits in a cue
* `clean`: drops the loop lines "Wer schön sein will, der muss auch lebt", "Du bist so schmerzhaft" and "Die Partei, verhoffnungslos"
* `clean`: drops "God bless the King, the King of Israel", an English line Whisper prints into German transcripts
* `clean`: strips a leading or trailing "#" used as a music note marker ("# Wir in Mexiko" becomes "Wir in Mexiko"). Only a # with a space next to it goes, so "#1" and hashtags stay
* `clean`: an output name with no extension, or one that cannot be written, now gives a one-line error and moves on to the next file instead of crashing with a Python traceback
* README and tests use the placeholder names Max and Erika Mustermann in the dubbing credit example instead of real people's names
* Tests for each new line, the # marker, and the output error, plus checks that the real proverb "Wer schön sein will, muss leiden." and a lone "Tschüss!" survive

Reasons for changes: These turned up repeated over and over in real German Whisper transcripts and the existing packs missed all of them. Some subtitle tools mark sung lines with # in place of ♪, which was left in the text. The traceback turned up while testing.

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
