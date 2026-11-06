"""Tests for subscrub. Run from the repo root with: python3 -m pytest"""

import os
import subprocess
import sys

import pysubs2
import pytest

import subscrub

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "subscrub.py")


def make(*cues):
    """Build an SSAFile from (start_s, end_s, text) tuples."""
    subs = pysubs2.SSAFile()
    for start, end, text in cues:
        subs.append(pysubs2.SSAEvent(start=int(start * 1000), end=int(end * 1000), text=text))
    return subs


def run(subs, **kw):
    opts = subscrub.Options(user_patterns=False, **kw)
    subscrub.clean(subs, opts, subscrub.Report(quiet=True))
    return [e.plaintext for e in subs]


def texts(*lines, **kw):
    """Clean one cue per line, three seconds apart, return the kept texts."""
    return run(make(*[(i * 3, i * 3 + 2, t) for i, t in enumerate(lines)]), **kw)


# --- hallucinations -------------------------------------------------------

@pytest.mark.parametrize("line", [
    "I'll see you next time.", "We'll see you next time.", "Thank you.",
    "We'll be right back.", "Stay tuned!", "Please like and subscribe",
    "Vielen Dank fürs Zuschauen!", "Bis zum nächsten Mal.",
    "¡Gracias por ver el video!", "Merci d'avoir regardé.", "Продолжение следует...",
    "ご視聴ありがとうございました", "2017",
])
def test_drops_outros(line):
    assert texts(line, "Real line here") == ["Real line here"]


def test_keep_thanks():
    assert texts("Thank you.", keep_thanks=True) == ["Thank you."]


@pytest.mark.parametrize("line", [
    "Untertitel im Auftrag des ZDF, 2020",
    "Untertitel im Auftrag des ZDF für funk, 2017",
    "Untertitelung des",
    "für funk,",
    "2017 Applaus",
    "Sprecher Jochen Graf Deutsche Bearbeitung sub&dub company Redaktion Julian Windisch",
    "Untertitel der Amara.org-Community",
    "Subtitles by the Amara.org community",
    "Subtítulos realizados por la comunidad de Amara.org",
])
def test_drops_credits(line):
    assert texts(line) == []


def test_cuts_credit_inside_real_line():
    assert texts("real words fur funk", "fur funk real words 2017 applaus") == ["real words", "real words"]


def test_role_word_in_real_line_kept():
    assert texts("Ich bin der Sprecher meiner Seele") == ["Ich bin der Sprecher meiner Seele"]


# --- sound tags and notes -------------------------------------------------

@pytest.mark.parametrize("line", [
    "* Musik *", "*", "Musik *", "* Jubel und Applaus *", "* Schreie *",
    "[Music]", "(applause)", "*crowd cheering*", "[Música]", "♪", "♪ ♫",
])
def test_drops_sound_tags(line):
    assert texts(line) == []


def test_sound_word_in_real_line_kept():
    assert texts("Lasset die Musik erklingen", "Ich liebe die Musik") == \
        ["Lasset die Musik erklingen", "Ich liebe die Musik"]


def test_notes_stripped_inside_line():
    assert texts("♪ Some real words ♪") == ["Some real words"]


def test_keep_sound_tags():
    assert texts("[Music]", keep_sound_tags=True) == ["[Music]"]


def test_strip_all_tags():
    assert texts("[door slams] Who is there?", strip_all_tags=True) == ["Who is there?"]


# --- loops ----------------------------------------------------------------

def test_word_loop_collapse():
    assert texts("go " * 12 + "now", max_word_repeat=3) == ["go go go now"]


def test_word_loops_left_alone_by_default():
    assert texts("oh oh oh oh oh oh") == ["oh oh oh oh oh oh"]


def test_repeat_cues():
    out = run(make(*[(i * 2, i * 2 + 1.5, "Same line") for i in range(8)]), max_repeats=2)
    assert out == ["Same line", "Same line"]


# --- layout ---------------------------------------------------------------

def test_long_cue_split_and_wrapped():
    text = ("This line is going on and on, it keeps going. And here is a second "
            "sentence that also runs long. Then a third one shows up here.")
    subs = make((0, 20, text))
    out = run(subs)
    assert len(out) > 1
    for line in "\n".join(out).split("\n"):
        assert len(line) <= 42
    assert " ".join(o.replace("\n", " ") for o in out) == text
    assert subs[0].start == 0 and subs[-1].end == 20000


def test_duration_split_needs_a_real_break():
    # On screen long, short text, no break point: left alone.
    assert texts_long("held note forever") == ["held note forever"]


def texts_long(text):
    return run(make((0, 15, text)))


def test_cjk_wrap():
    text = "今天天气很好我们去公园散步吧然后一起吃饭"
    out = run(make((0, 4, text)))
    for line in "\n".join(out).split("\n"):
        assert len(line) <= 16


def test_existing_good_wrap_kept():
    assert texts("Short top line\nShort bottom line") == ["Short top line\nShort bottom line"]


# --- timing ---------------------------------------------------------------

def test_overlap_fixed():
    subs = make((0, 5, "First line"), (4, 8, "Second line"))
    run(subs)
    assert subs[0].end <= subs[1].start


def test_small_gap_closed_big_gap_kept():
    subs = make((0, 2, "One"), (2.5, 4, "Two"), (10, 12, "Three"))
    run(subs)
    assert subs[1].start - subs[0].end == 42
    assert subs[2].start - subs[1].end > 5000


def test_flash_cue_stretched():
    subs = make((0, 0.3, "Quick"), (5, 6, "Next"))
    run(subs)
    assert subs[0].end - subs[0].start >= 1200


# --- patterns file --------------------------------------------------------

def test_user_patterns(tmp_path):
    pf = tmp_path / "p.conf"
    pf.write_text("# comment\ndrop totally fake line\ncut \\bjunkword\\b\n", encoding="utf-8")
    out = run(make((0, 2, "totally fake line"), (3, 5, "keep junkword this")),
              pattern_files=[str(pf)])
    assert out == ["keep this"]


def test_bad_patterns_file(tmp_path):
    pf = tmp_path / "p.conf"
    pf.write_text("nonsense line\n", encoding="utf-8")
    with pytest.raises(ValueError):
        subscrub.build_rules(["en"], [str(pf)], False)


# --- files and CLI --------------------------------------------------------

def cli(*args):
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True)


@pytest.mark.parametrize("ext", [".srt", ".vtt", ".ass"])
def test_formats_round_trip(tmp_path, ext):
    src = tmp_path / ("in" + ext)
    make((0, 2, "Hello there"), (3, 5, "[Music]"), (6, 8, "Thank you.")).save(str(src))
    r = cli("clean", "-q", str(src))
    assert r.returncode == 0, r.stderr
    out = pysubs2.load(str(tmp_path / ("in.clean" + ext)))
    assert [e.plaintext for e in out] == ["Hello there"]


def test_format_conversion(tmp_path):
    src = tmp_path / "in.srt"
    make((0, 2, "Hello there")).save(str(src))
    r = cli("clean", "-q", "--format", "vtt", str(src))
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "in.clean.vtt").read_text(encoding="utf-8").startswith("WEBVTT")


def test_dry_run_writes_nothing(tmp_path):
    src = tmp_path / "in.srt"
    make((0, 2, "Hello there")).save(str(src))
    r = cli("clean", "-n", str(src))
    assert r.returncode == 0
    assert not (tmp_path / "in.clean.srt").exists()


def test_in_place_keeps_backup(tmp_path):
    src = tmp_path / "in.srt"
    make((0, 2, "Hello there"), (3, 5, "Thank you.")).save(str(src))
    r = cli("clean", "-q", "--in-place", str(src))
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "in.srt.bak").exists()
    assert len(pysubs2.load(str(src))) == 1


def test_cp1252_fallback(tmp_path):
    src = tmp_path / "in.srt"
    src.write_bytes("1\n00:00:01,000 --> 00:00:03,000\nGr\xfc\xdfe\n".encode("latin-1"))
    r = cli("clean", "-q", str(src))
    assert r.returncode == 0, r.stderr
    assert pysubs2.load(str(tmp_path / "in.clean.srt"))[0].plaintext == "Grüße"


def test_splice():
    subs = make((0, 2, "keep"), (10, 12, "old a"), (14, 16, "old b"), (30, 32, "keep too"))
    new = make((11, 13, "new a"), (15, 25, "new b"))
    subscrub.splice(subs, new, 9000, 20000, subscrub.Report(quiet=True))
    assert [e.plaintext for e in subs] == ["keep", "new a", "new b", "keep too"]
    assert subs[2].end == 20000


def test_parse_time():
    assert subscrub.parse_time("1:01:03.5") == 3663500
    assert subscrub.parse_time("17:26") == 1046000
    assert subscrub.parse_time("90") == 90000
