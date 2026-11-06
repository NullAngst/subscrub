#!/usr/bin/env python3
"""Subscrub: clean up machine-generated subtitles.

Built for Whisper output (whisper.cpp, faster-whisper, WhisperX, Subtitle
Edit, Buzz), but works on any subtitle file: SRT, WebVTT, ASS/SSA and the
other formats pysubs2 reads.

Commands:
  clean       Remove hallucinated lines, credits and sound tags, fix overlaps,
              split overlong cues, rewrap lines, fix flash and blink timing.
  transcribe  Make subtitles from a video or audio file with ffmpeg and
              whisper.cpp, then clean them.
  redo        Re-transcribe one time range in a forced language and splice
              it into an existing subtitle file.
  patterns    List the built-in patterns and where the user file goes.
"""

import argparse
import dataclasses
import os
import re
import shutil
import subprocess
import sys
import tempfile

__version__ = "1.0.0"
PROG = "subscrub"

try:
    import pysubs2
except ImportError:
    sys.stderr.write(
        f"{PROG}: missing Python module 'pysubs2'.\n"
        "Install subscrub with pipx (see README.md), which pulls it in, or\n"
        "install pysubs2 into the venv you run this from.\n"
    )
    sys.exit(1)


# ===========================================================================
# Patterns
# ===========================================================================
# Two kinds of rule:
#   drop  the whole cue matches: the cue is deleted.
#   cut   the match is removed from wherever it sits in the cue; the cue is
#         deleted if nothing readable is left.
# Each rule has a label that shows up in the report. Rules labelled "thanks"
# are skipped with --keep-thanks.
#
# Everything here is matched case-insensitive unless a rule sets case=True.
# These are lines Whisper invents over music, silence or noise. They come
# from its training data: YouTube outros, TV captions, fan-sub credits.

@dataclasses.dataclass
class Rule:
    kind: str          # "drop" or "cut"
    pattern: str
    label: str
    case: bool = False
    rx: object = None

    def compile(self):
        flags = 0 if self.case else re.I
        if self.kind == "drop":
            self.rx = re.compile(r"^\s*(?:" + self.pattern + r")\s*$", flags)
        else:
            self.rx = re.compile(self.pattern, flags)
        return self


def D(pattern, label, case=False):
    return Rule("drop", pattern, label, case)


def C(pattern, label="credit", case=False):
    return Rule("cut", pattern, label, case)


P = r"[.!。！]?"   # optional end punctuation

BUILTIN = {
    "en": [
        D(r"(i'?ll|we'?ll|i will|we will) see you (all )?(next time|soon|in the next (video|one))" + P, "outro"),
        D(r"(thanks|thank you)( (so|very) much)?( (all|everyone|guys))?( for watching)?" + P, "thanks"),
        D(r"(we'?ll|we will|i'?ll) be right back" + P, "TV break"),
        D(r"(stay tuned|don'?t go anywhere)" + P + r"( we'?ll be right back" + P + r")?", "TV break"),
        D(r"(coming up|up next)( (next|after the break))?" + P, "TV break"),
        D(r"(please )?(like and )?subscribe[^.\n]*" + P, "outro"),
        D(r"(please )?(like|share)(,)? (and )?(comment|subscribe)[^.\n]*" + P, "outro"),
        C(r"[^.\n]*amara\.org[^.\n]*\.?", "credit"),
        C(r"\b(translated|transcribed|subtitled|captioned|subtitles|captions|transcription) by [^.\n]*", "credit"),
        C(r"\bsubtitles? (made|created) (with|by) [^.\n]*", "credit"),
        C(r"\bcopyright\b[^\n]*\b(19|20)\d{2}\b[^.\n]*\.?", "credit"),
    ],
    "de": [
        D(r"wir sind gleich wieder (da|zur(ü|ue)ck)" + P, "TV break"),
        D(r"bis zum n(ä|ae)chsten (mal|video)" + P, "outro"),
        D(r"(vielen )?dank( f(ü|ue)rs (zuschauen|zusehen))?" + P, "thanks"),
        D(r"(abonniert|abonniere)[^.\n]*" + P, "outro"),
        # The ZDF/funk credit, whole and in the pieces Whisper splits it into.
        C(r"\buntertitel(ung)?\b[^\n]*?\b(zdf|ard|wdr|ndr|br|swr|mdr|hr|rbb|funk|sat\.?1|rtl)\b( f(ü|ue)r funk)?,?\s*((19|20)\d{2})?\.?"),
        C(r"\b(zdf|ard|wdr|swr|ndr|mdr)( f(ü|ue)r funk)?,? (19|20)\d{2}\.?"),
        C(r"\buntertitel(ung)?\b( (im auftrag|von|der|des|f(ü|ue|u)r))*( (des|der))?"),
        C(r"\bim auftrag (des|der|von)( (zdf|ard|wdr|ndr|swr|mdr|rbb))?\b"),
        C(r"\bf(ü|ue|u)r funk\b,?"),
        C(r"\b(19|20)\d{2},?\s+(applaus|jubel)\b"),
        # Dubbing credits from German-dubbed TV documentaries. The role word
        # matches in any case, the name after it only when capitalised.
        C(r"\b(?i:sub\s*&\s*dub)( (?i:company))?\b", case=True),
        C(r"\b(?i:deutsche (bearbeitung|fassung|synchronfassung|(ü|ue)bersetzung|synchronisation|untertitel))\b", case=True),
        C(r"\b(?i:synchronfassung|synchronisation|synchronregie|dialogbuch|dialogregie)\b(\s*:?\s+NAME(\s+NAME)?)?", case=True),
        C(r"\b(?i:sprecher(in)?|sprecherinnen|redaktion|(ü|ue)bersetzung|regie|mischung|aufnahmeleitung|produktion)\s*:?\s+NAME(\s+NAME)?", case=True),
    ],
    "es": [
        D(r"¡?(muchas )?gracias( por (ver|mirar|su atenci[oó]n|vernos))?( el (video|v[ií]deo))?" + P, "thanks"),
        D(r"¡?suscr[ií]bete[^.\n]*" + P, "outro"),
        D(r"¡?(nos vemos|hasta) (en el pr[oó]ximo (video|v[ií]deo)|la pr[oó]xima)" + P, "outro"),
        C(r"\bsubt[ií]tulos? (realizados?|hechos?|creados?) por [^.\n]*"),
        C(r"\bsubtitulado por [^.\n]*"),
    ],
    "fr": [
        D(r"merci( beaucoup)?( (d'avoir regard[ée]|de votre attention|à tous|pour votre attention))?" + P, "thanks"),
        D(r"abonnez-vous[^.\n]*" + P, "outro"),
        D(r"(à|a) (la prochaine|bient[oô]t)" + P, "outro"),
        C(r"\bsous-titr(es|age)( (réalisés?|faits?))? (par|de) [^.\n]*"),
        C(r"\bsous-titrage st' ?\d+\.?"),
    ],
    "it": [
        D(r"grazie( mille)?( (a tutti|per (la visione|l'attenzione|aver guardato)))?" + P, "thanks"),
        D(r"iscriviti[^.\n]*" + P, "outro"),
        C(r"\bsottotitoli( e revisione)? (creati|a cura|realizzati)[^.\n]*"),
        C(r"\bqtss\b"),
    ],
    "pt": [
        D(r"obrigad[oa]( (a todos|por assistir(em)?))?" + P, "thanks"),
        D(r"inscreva-se[^.\n]*" + P, "outro"),
        C(r"\blegendas? (pela|por|feitas por) [^.\n]*"),
    ],
    "nl": [
        D(r"(bedankt|dank je( wel)?)( voor het kijken)?" + P, "thanks"),
        D(r"abonneer[^.\n]*" + P, "outro"),
        C(r"\bondertitel(d|ing) (door|van) [^.\n]*"),
    ],
    "ru": [
        D(r"спасибо( за (просмотр|внимание))?" + P, "thanks"),
        D(r"продолжение следует\.*", "outro"),
        D(r"подписывайтесь[^.\n]*" + P, "outro"),
        C(r"\bсубтитры (сделал|создавал|подогнал|делал|от)[^.\n]*"),
        C(r"\bредактор субтитров[^.\n]*"),
        C(r"\bкорректор [^.\n]*"),
    ],
    "ja": [
        D(r"(ご視聴)?(本当に)?ありがとうございました" + P, "thanks"),
        D(r"[^\n]*チャンネル登録[^\n]*", "outro"),
    ],
    "zh": [
        D(r"(谢谢|感谢)(大家|您)?的?(观看|收看)?" + P, "thanks"),
        D(r"[^\n]*(点赞|订阅|转发|打赏)[^\n]*(点赞|订阅|转发|打赏)[^\n]*", "outro"),
        C(r"字幕(由|制作|提供)[^\n。]*。?"),
        C(r"[^\n]*明镜[^\n]*点点[^\n]*"),
    ],
    "ko": [
        D(r"(시청|구독)?\s?(해\s?주셔서|해주셔서)?\s?감사합니다" + P, "thanks"),
        D(r"[^\n]*구독과 좋아요[^\n]*", "outro"),
        C(r"MBC ?뉴스 ?[^\n]*입니다\.?"),
    ],
    "any": [
        D(r"[#\s*.\-_~]+", "junk"),
        D(r"((19|20)\d{2}[\s,.]*)+", "stray year"),
    ],
}

_NAME = r"[A-ZÄÖÜ][\wäöüß.'-]+"
for _rules in BUILTIN.values():
    for _r in _rules:
        _r.pattern = _r.pattern.replace("NAME", _NAME)

# Sound tags. Whisper writes these as "* Musik *", "[Music]", "(applause)",
# "*crowd cheering*", and often splits them over two cues, leaving "*" in one
# and "Musik *" in the next. A sound word is only removed when it sits next
# to a tag marker, so "die Musik" in a real line stays. Crowd words (applause
# and friends) are also removed bare at the start or end of a cue.
SOUND_WORDS = (
    r"(music|musik|m[uú]sica|musique|musica|muziek|музыка|音楽|音乐|음악|"
    r"applause|applaus|aplausos?|applaudissements|applausi|beifall|аплодисменты|"
    r"cheering|cheers|jubel|ovaci[oó]n|"
    r"laughter|laughing|lachen|gel(ä|ae)chter|risas|rires|risate|risos|gelach|смех|"
    r"screaming|screams|schreie|schreien|gritos|cris|"
    r"singing|gesang|instrumental|noise|ger(ä|ae)usche|silence|stille|silencio|"
    r"crowd( cheering| noise)?|upbeat music|dramatic music|soft music)"
)
CROWD_WORDS = r"(applause|applaus|aplausos?|applaudissements|applausi|beifall|cheering|jubel)"


def _run(words):
    return words + r"((\s+(und|and|&|y|et|e|en|и)\s+|\s+)" + words + r")*"


SW_RUN, CROWD_RUN = _run(SOUND_WORDS), _run(CROWD_WORDS)
SOUND_TAG_RE = [
    re.compile(r"[*\[(（【]\s*(?:" + SW_RUN + r")?\s*[*\])）】]", re.I),   # * Musik *, [Music]
    re.compile(r"[*\[(（【]\s*" + SW_RUN, re.I),                       # "* Musik" (tail cut off)
    re.compile(r"\b" + SW_RUN + r"\s*[*\])）】]", re.I),               # "Musik *" (head cut off)
    re.compile(r"(^|\s)" + CROWD_RUN + r"[.!]?\s*$", re.I),
    re.compile(r"^\s*" + CROWD_RUN + r"[.!]?(\s|$)", re.I),
    re.compile(r"(^|\s)\*+(\s|$)"),                                    # lone asterisks
]
SOUND_ONLY_RE = re.compile(r"^\s*" + SW_RUN + r"[.!]?\s*$", re.I)
# --strip-all-tags: any short bracketed or starred tag, e.g. "[door slams]".
ANY_TAG_RE = re.compile(r"\[[^\]\n]{1,40}\]|\([^)\n]{1,40}\)|\*[^*\n]{1,40}\*|（[^）\n]{1,40}）|【[^】\n]{1,40}】")

# Music notes: U+2669 to U+266C, plus emoji notes U+1F3B5 and U+1F3B6.
NOTES_RE = re.compile("[♩-♬\U0001F3B5\U0001F3B6]")


def user_patterns_path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, PROG, "patterns.conf")


def load_pattern_file(path):
    """Read a patterns file. Each line: 'drop REGEX', 'cut REGEX', or the
    same with '-case' (drop-case, cut-case) for case-sensitive. # comments."""
    rules = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            kind, _, pat = line.partition(" ")
            pat = pat.strip()
            case = kind.endswith("-case")
            kind = kind[:-5] if case else kind
            if kind not in ("drop", "cut") or not pat:
                raise ValueError(f"{path}:{n}: expected 'drop REGEX' or 'cut REGEX'")
            try:
                rules.append(Rule(kind, pat, "user", case).compile())
            except re.error as e:
                raise ValueError(f"{path}:{n}: bad regex: {e}")
    return rules


def build_rules(langs, extra_files, use_user_file):
    if langs == ["all"]:
        langs = [k for k in BUILTIN if k != "any"]
    unknown = [l for l in langs if l not in BUILTIN]
    if unknown:
        raise ValueError("unknown language pack: " + ", ".join(unknown)
                         + " (have: " + ", ".join(k for k in BUILTIN if k != "any") + ")")
    rules = [r.compile() for l in langs + ["any"] for r in BUILTIN[l]]
    files = list(extra_files)
    if use_user_file and os.path.isfile(user_patterns_path()):
        files.append(user_patterns_path())
    for path in files:
        rules += load_pattern_file(path)
    return rules


# ===========================================================================
# Text helpers
# ===========================================================================
DE_WORDS = set(
    "und ich die der das nicht ist ein eine mich mir dich dir wenn doch auf mit "
    "zu es sie wir du ihr mein dein kein im auch nur noch so wie was bin bist hat "
    "sind wird alle alles dann denn den dem des ach nein ja oder aus".split()
)
# Capitalised mid-text, these nearly always start a new line in German.
# German capitalises every noun, so a plain capital-letter test is useless.
DE_LINE_STARTERS = set(
    "Und Doch Wenn Denn Ich Du Er Es Wir Ihr Der Die Das Ein Eine Mein Dein Kein "
    "Im In Auf Aus Mit Ohne Hat Ist Bist Alle Alles Dann Da So Ach Oh Ja Nein Was "
    "Wer Wie Warum Man Nur Hier Jeder Jede Niemand Immer Nie Lass Lasset Gib Komm".split()
)
# Capitalised mid-line in English for reasons other than a new line.
EN_ALWAYS_CAPS = {"I", "I'm", "I'd", "I'll", "I've", "God", "Mr", "Mrs", "Dr"}
CJK_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯＀-￯]")
GERMANIC_EXTRA = re.compile(r"[äöüß]", re.I)


def script_of(text):
    """'cjk' for mostly-CJK text, 'de' for German, 'latin' for everything else."""
    letters = [c for c in text if c.isalpha()]
    if letters and sum(bool(CJK_RE.match(c)) for c in letters) / len(letters) > 0.3:
        return "cjk"
    words = re.findall(r"[^\W\d_]+", text.lower())
    de = sum(w in DE_WORDS for w in words) + 2 * len(GERMANIC_EXTRA.findall(text))
    return "de" if de >= max(2, len(words) // 5) else "latin"


def tokens_of(text, script):
    """Break units: words for spaced scripts, characters for CJK."""
    if script == "cjk" and " " not in text.strip():
        return list(text), ""
    return text.split(), " "


def break_score(prev, nxt, script):
    """How good a spot to break between two tokens (0 is poor)."""
    if re.search(r"[.!?。！？…]['\")」』]*$", prev):
        return 4
    if re.search(r"[,;:、，；：]['\")」』]*$", prev):
        return 3
    if script == "cjk":
        return 0
    bare = nxt.strip("\"'(¡¿")
    if not bare or not bare[0].isupper():
        return 0
    word = bare.rstrip(",.!?")
    if script == "de":
        return 2 if word in DE_LINE_STARTERS else 0
    return 0 if word in EN_ALWAYS_CAPS else 2


def best_break(toks, joiner, script, target, min_score=0, max_side=None):
    """Index i to break before toks[i]. Prefers good breaks near target chars.

    min_score: skip breaks scoring lower than this.
    max_side:  skip breaks leaving either side longer than this, if any
               break manages that.
    """
    total = len(joiner.join(toks))
    best_i, best_val = None, None
    pos = 0
    for i in range(1, len(toks)):
        pos += len(toks[i - 1]) + len(joiner)
        score = break_score(toks[i - 1], toks[i], script)
        if score < min_score:
            continue
        if max_side and (pos - len(joiner) > max_side or total - pos > max_side):
            continue
        # One score point is worth about a quarter of the line in distance.
        val = score * max(4, total // 8) - abs(pos - target)
        if best_val is None or val > best_val:
            best_i, best_val = i, val
    if best_i is None and max_side:
        return best_break(toks, joiner, script, target, min_score)
    return best_i


def normalise(text):
    text = text.replace("\\N", " ").replace("\\n", " ").replace("\n", " ")
    text = NOTES_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^(-\s*)+(?=\S)", "", text)      # stray dialogue dashes
    return text.strip()


def collapse_word_loops(text, keep):
    """Cut a word or short phrase repeated more than `keep` times in a row
    down to `keep` repeats. Catches Whisper's 'the the the the the' loops."""
    words = text.split()
    key = [re.sub(r"[^\w']", "", w.lower()) for w in words]
    out, i = [], 0
    while i < len(words):
        done = False
        for k in range(1, 5):
            unit = key[i:i + k]
            if len(unit) < k or not all(unit):
                break
            n = 1
            while key[i + n * k:i + (n + 1) * k] == unit:
                n += 1
            if n > keep:
                out += words[i:i + keep * k]
                i += n * k
                done = True
                break
        if not done:
            out.append(words[i])
            i += 1
    return " ".join(out)


def has_letters(text):
    return bool(re.search(r"[^\W\d_]", text))


def fmt_ms(ms):
    return pysubs2.time.ms_to_str(ms, fractions=True)


# ===========================================================================
# Cleaning
# ===========================================================================
@dataclasses.dataclass
class Options:
    langs: list = dataclasses.field(default_factory=lambda: ["all"])
    pattern_files: list = dataclasses.field(default_factory=list)
    user_patterns: bool = True
    keep_thanks: bool = False
    keep_sound_tags: bool = False
    strip_all_tags: bool = False
    max_word_repeat: int = 0
    max_repeats: int = 0
    max_chars: int = 42
    max_chars_cjk: int = 16
    max_lines: int = 2
    max_dur: int = 7000
    min_dur: int = 1200
    close_gap: int = 800
    gap: int = 42
    no_split: bool = False
    no_timing: bool = False


class Report:
    def __init__(self, quiet=False):
        self.quiet = quiet
        self.counts = {}

    def note(self, ev, what, detail):
        self.counts[what] = self.counts.get(what, 0) + 1
        if not self.quiet:
            sys.stderr.write(f"{fmt_ms(ev.start)}  {what}: {detail}\n")

    def say(self, msg):
        if not self.quiet:
            sys.stderr.write(msg + "\n")


def scrub_text(subs, rules, o, rep):
    """Per-cue text clean-up. Cues whose text ends up unchanged keep their
    original markup, so styled ASS files are not flattened for nothing."""
    drops = [r for r in rules if r.kind == "drop" and not (o.keep_thanks and r.label == "thanks")]
    cuts = [r for r in rules if r.kind == "cut"]
    kept = []
    for ev in subs:
        if ev.is_comment:
            kept.append(ev)
            continue
        flat = re.sub(r"\s+", " ", ev.plaintext).strip()
        orig = normalise(ev.plaintext)
        text = orig
        for r in cuts:
            m = r.rx.search(text)
            if m:
                rep.note(ev, f"cut {r.label}", repr(m.group(0).strip()))
                text = normalise(r.rx.sub(" ", text))
        if o.strip_all_tags:
            t2 = normalise(ANY_TAG_RE.sub(" ", text))
            if t2 != text:
                rep.note(ev, "cut tag", f"{text!r} -> {t2!r}")
                text = t2
        if not o.keep_sound_tags:
            before = text
            if SOUND_ONLY_RE.match(text):
                text = ""
            for rx in SOUND_TAG_RE:
                text = normalise(rx.sub(" ", text))
            if text != before:
                if has_letters(text):
                    rep.note(ev, "cut sound tag", f"{before!r} -> {text!r}")
                else:
                    rep.note(ev, "dropped sound tag", repr(before))
                    continue
        if o.max_word_repeat:
            t2 = collapse_word_loops(text, o.max_word_repeat)
            if t2 != text:
                rep.note(ev, "collapsed loop", f"{len(text.split())} -> {len(t2.split())} words")
                text = t2
        if not re.search(r"\w", text):
            if orig:
                rep.note(ev, "dropped empty", repr(orig))
            continue
        hit = next((r for r in drops if r.rx.match(text)), None)
        if hit:
            rep.note(ev, f"dropped {hit.label}", repr(text))
            continue
        if text != flat:
            ev.plaintext = text
        kept.append(ev)
    subs.events = kept


def collapse_repeat_cues(subs, keep, rep):
    """Drop a cue repeated more than `keep` times in a row (Whisper loops)."""
    out, run, last = [], 0, None
    for ev in subs:
        key = normalise(ev.plaintext).lower()
        run = run + 1 if key == last else 1
        last = key
        if run > keep:
            rep.note(ev, "dropped repeat", repr(normalise(ev.plaintext)))
            continue
        out.append(ev)
    subs.events = out


def dialogue(subs):
    return [e for e in subs if not e.is_comment]


def fix_overlaps(subs, gap):
    subs.sort()
    evs = dialogue(subs)
    for a, b in zip(evs, evs[1:]):
        if a.end > b.start - gap:
            a.end = max(a.start + 1, b.start - gap)


def line_limit(o, script):
    return o.max_chars_cjk if script == "cjk" else o.max_chars


def split_long(subs, o):
    out = []
    for ev in subs:
        if ev.is_comment:
            out.append(ev)
            continue
        text0 = normalise(ev.plaintext)
        stack, pieces = [(ev.start, ev.end, text0)], []
        while stack:
            start, end, text = stack.pop(0)
            script = script_of(text)
            toks, joiner = tokens_of(text, script)
            limit = line_limit(o, script) * o.max_lines
            i = None
            if len(toks) >= 2 and (end - start) >= 2 * o.min_dur:
                if len(text) > limit:
                    # Too much text to show at once: split at the best break.
                    i = best_break(toks, joiner, script, len(text) / 2)
                elif (end - start) > o.max_dur:
                    # Only on screen too long: split at a real sentence or
                    # line break, or leave it.
                    i = best_break(toks, joiner, script, len(text) / 2, min_score=2)
            if i is None:
                pieces.append((start, end, text))
                continue
            left, right = joiner.join(toks[:i]), joiner.join(toks[i:])
            # Share the time out by character count.
            cut = start + round((end - start) * len(left) / (len(left) + len(right)))
            stack[0:0] = [(start, cut, left), (cut, end, right)]
        if len(pieces) == 1:
            out.append(ev)
            continue
        for start, end, text in pieces:
            p = ev.copy()
            p.start, p.end, p.plaintext = start, end, text
            out.append(p)
    subs.events = out


def wrap(subs, o):
    for ev in dialogue(subs):
        lines = ev.plaintext.split("\n")
        text = normalise(ev.plaintext)
        script = script_of(text)
        lim = line_limit(o, script)
        if len(lines) <= o.max_lines and all(len(l) <= lim for l in lines):
            continue
        if len(text) <= lim:
            ev.plaintext = text
            continue
        toks, joiner = tokens_of(text, script)
        i = best_break(toks, joiner, script, len(text) / 2, max_side=lim)
        if i:
            ev.plaintext = joiner.join(toks[:i]) + "\n" + joiner.join(toks[i:])


def fix_timing(subs, o):
    subs.sort()
    evs = dialogue(subs)
    for idx, ev in enumerate(evs):
        nxt = evs[idx + 1].start if idx + 1 < len(evs) else None
        hole = (nxt - ev.end) if nxt is not None else None
        # Close tiny gaps so subtitles do not blink off and on.
        if hole is not None and 0 < hole <= o.close_gap:
            ev.end = nxt - o.gap
        # Stretch flash cues, never into the next cue.
        if ev.end - ev.start < o.min_dur:
            want = ev.start + o.min_dur
            ev.end = max(ev.end, min(want, nxt - o.gap) if nxt is not None else want)


def clean(subs, o, rep, rules=None):
    if rules is None:
        rules = build_rules(o.langs, o.pattern_files, o.user_patterns)
    before = len(dialogue(subs))
    subs.sort()
    scrub_text(subs, rules, o, rep)
    if o.max_repeats:
        collapse_repeat_cues(subs, o.max_repeats, rep)
    fix_overlaps(subs, o.gap)
    if not o.no_split:
        split_long(subs, o)
    wrap(subs, o)
    if not o.no_timing:
        fix_timing(subs, o)
    fix_overlaps(subs, o.gap)
    rep.say(f"cues: {before} in, {len(dialogue(subs))} out")
    return subs


# ===========================================================================
# Files
# ===========================================================================
EXT_FORMAT = {".srt": "srt", ".vtt": "vtt", ".ass": "ass", ".ssa": "ssa",
              ".sub": "microdvd", ".json": "json", ".txt": "tmp"}


def load_subs(path, encoding, rep):
    if encoding:
        return pysubs2.load(path, encoding=encoding)
    try:
        return pysubs2.load(path, encoding="utf-8-sig")
    except UnicodeDecodeError:
        rep.say(f"{path}: not UTF-8, reading as Windows-1252 (use --encoding to change)")
        return pysubs2.load(path, encoding="cp1252")


def out_path(inp, a, fmt_ext):
    if a.in_place:
        return inp
    stem, ext = os.path.splitext(inp)
    stem = re.sub(r"\.clean$", "", stem)
    name = stem + ".clean" + (fmt_ext or ext)
    if a.out_dir:
        name = os.path.join(a.out_dir, os.path.basename(name))
    return name


def save_subs(subs, path, fmt):
    kw = {"encoding": "utf-8"}
    if fmt:
        kw["format_"] = fmt
    if (fmt or EXT_FORMAT.get(os.path.splitext(path)[1].lower())) == "microdvd":
        kw["fps"] = subs.info.get("fps") or 25
    subs.save(path, **kw)


# ===========================================================================
# Whisper (ffmpeg + whisper.cpp)
# ===========================================================================
def parse_time(s):
    """1:23:45.6, 23:45 or plain seconds, to milliseconds."""
    try:
        secs = 0.0
        for part in s.replace(",", ".").split(":"):
            secs = secs * 60 + float(part)
    except ValueError:
        raise argparse.ArgumentTypeError(f"bad time: {s}")
    return round(secs * 1000)


def find_whisper(override):
    for cand in [override, os.environ.get("SUBSCRUB_WHISPER"),
                 shutil.which("whisper-cli"), shutil.which("whisper-cpp")]:
        if cand and os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


def run_whisper(a, media, lang, start=None, end=None):
    """Transcribe media (or the start..end slice of it). Returns SSAFile with
    times relative to the start of the media file."""
    ffmpeg = shutil.which("ffmpeg")
    whisper = find_whisper(a.whisper)
    model = a.model or os.environ.get("SUBSCRUB_MODEL")
    missing = []
    if not ffmpeg:
        missing.append("ffmpeg")
    if not whisper:
        missing.append("whisper-cli (put it on PATH, set SUBSCRUB_WHISPER, or pass --whisper)")
    if not model or not os.path.isfile(model):
        missing.append("model file (pass --model or set SUBSCRUB_MODEL)")
    if not os.path.isfile(media):
        missing.append(f"media file {media}")
    if missing:
        die("missing: " + "; ".join(missing))
    vad = a.vad_model or os.environ.get("SUBSCRUB_VAD_MODEL")
    if vad and not os.path.isfile(vad):
        die(f"VAD model not found: {vad}")

    with tempfile.TemporaryDirectory(prefix=f"{PROG}.") as tmp:
        wav = os.path.join(tmp, "audio.wav")
        prefix = os.path.join(tmp, "audio")
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
        if start is not None:
            cmd += ["-ss", f"{start / 1000:.3f}"]
        cmd += ["-i", media]
        if start is not None and end is not None:
            cmd += ["-t", f"{(end - start) / 1000:.3f}"]
        # whisper.cpp wants 16 kHz mono 16-bit PCM.
        cmd += ["-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav]
        subprocess.run(cmd, check=True)

        # -mc 0 stops earlier text being fed into later chunks, the main
        # cause of Whisper getting stuck in one language or one phrase.
        wcmd = [whisper, "-m", model, "-l", lang, "-mc", "0",
                "-osrt", "-of", prefix, "-f", wav]
        if vad:
            wcmd += ["--vad", "--vad-model", vad]
        if a.whisper_args:
            wcmd += a.whisper_args.split()      # split on spaces on purpose
        if not getattr(a, "quiet", False):
            sys.stderr.write("running: " + " ".join(wcmd) + "\n")
        subprocess.run(wcmd, check=True)
        new = pysubs2.load(prefix + ".srt", encoding="utf-8")
    if start:
        new.shift(ms=start)
    return new


def splice(subs, new, start, end, rep):
    """Replace cues whose middle falls in start..end with the new cues."""
    old = len(subs)
    subs.events = [e for e in subs if not (start <= (e.start + e.end) // 2 < end)]
    removed, added = old - len(subs), 0
    for ev in new:
        ev.end = min(ev.end, end)
        if ev.end > ev.start:
            subs.append(ev)
            added += 1
    subs.sort()
    rep.say(f"replaced {removed} cues with {added} in {fmt_ms(start)} - {fmt_ms(end)}")


# ===========================================================================
# CLI
# ===========================================================================
def die(msg, code=1):
    sys.stderr.write(f"{PROG}: {msg}\n")
    sys.exit(code)


def options_from(a):
    return Options(
        langs=a.lang_packs.split(",") if a.lang_packs else ["all"],
        pattern_files=a.patterns or [],
        user_patterns=not a.no_user_patterns,
        keep_thanks=a.keep_thanks, keep_sound_tags=a.keep_sound_tags,
        strip_all_tags=a.strip_all_tags, max_word_repeat=a.max_word_repeat,
        max_repeats=a.max_repeats, max_chars=a.max_chars, max_chars_cjk=a.max_chars_cjk,
        max_lines=a.max_lines, max_dur=a.max_dur, min_dur=a.min_dur,
        close_gap=a.close_gap, gap=a.gap, no_split=a.no_split, no_timing=a.no_timing,
    )


def add_clean_opts(sp):
    g = sp.add_argument_group("what to remove")
    g.add_argument("--lang-packs", metavar="LIST",
                   help="comma-separated pattern packs to use, e.g. en,de (default: all)")
    g.add_argument("--patterns", action="append", metavar="FILE",
                   help="extra patterns file, can be given more than once")
    g.add_argument("--no-user-patterns", action="store_true",
                   help=f"ignore {user_patterns_path()}")
    g.add_argument("--keep-thanks", action="store_true",
                   help="keep lone 'Thank you.' style cues")
    g.add_argument("--keep-sound-tags", action="store_true",
                   help="keep [Music], * Applaus * and similar tags")
    g.add_argument("--strip-all-tags", action="store_true",
                   help="remove every short [..], (..) or *..* tag, not only sound tags")
    g.add_argument("--max-word-repeat", type=int, default=0, metavar="N",
                   help="cut a word or phrase repeated more than N times in a row (off)")
    g.add_argument("--max-repeats", type=int, default=0, metavar="N",
                   help="drop a cue repeated more than N times in a row (off)")
    t = sp.add_argument_group("layout and timing")
    t.add_argument("--max-chars", type=int, default=42, help="characters per line (42)")
    t.add_argument("--max-chars-cjk", type=int, default=16, help="characters per line for CJK (16)")
    t.add_argument("--max-lines", type=int, default=2, help="lines per cue (2)")
    t.add_argument("--max-dur", type=int, default=7000, metavar="MS",
                   help="split cues on screen longer than this, if there is a real break (7000)")
    t.add_argument("--min-dur", type=int, default=1200, metavar="MS",
                   help="stretch cues shorter than this (1200)")
    t.add_argument("--close-gap", type=int, default=800, metavar="MS",
                   help="close gaps up to this size (800)")
    t.add_argument("--gap", type=int, default=42, metavar="MS",
                   help="gap left between cues, about one frame (42)")
    t.add_argument("--no-split", action="store_true", help="never split cues")
    t.add_argument("--no-timing", action="store_true", help="leave gaps and short cues alone")


def add_output_opts(sp, single=False):
    g = sp.add_argument_group("output")
    g.add_argument("-o", "--output", metavar="FILE", help="output file" + ("" if single else " (one input only)"))
    if not single:
        g.add_argument("--out-dir", metavar="DIR", help="write outputs here")
        g.add_argument("--in-place", action="store_true", help="overwrite inputs, keeping a .bak copy")
    g.add_argument("--format", choices=sorted(set(EXT_FORMAT.values())),
                   help="output format (default: from the output name, else same as input)")
    g.add_argument("--encoding", help="input encoding (default: UTF-8, falls back to Windows-1252)")
    g.add_argument("-n", "--dry-run", action="store_true", help="report only, write nothing")
    g.add_argument("-q", "--quiet", action="store_true", help="no report")


def add_whisper_opts(sp):
    g = sp.add_argument_group("whisper")
    g.add_argument("--model", metavar="FILE", help="whisper.cpp model, e.g. ggml-large-v3.bin (or SUBSCRUB_MODEL)")
    g.add_argument("--whisper", metavar="FILE", help="path to whisper-cli (or SUBSCRUB_WHISPER)")
    g.add_argument("--vad-model", metavar="FILE",
                   help="Silero VAD model, skips non-speech before transcribing (or SUBSCRUB_VAD_MODEL)")
    g.add_argument("--whisper-args", metavar="ARGS", help="extra whisper-cli arguments, quoted")


def cmd_clean(a):
    if a.output and len(a.inputs) > 1:
        die("-o works with one input only, use --out-dir for several")
    if a.out_dir:
        os.makedirs(a.out_dir, exist_ok=True)
    o = options_from(a)
    try:
        rules = build_rules(o.langs, o.pattern_files, o.user_patterns)
    except ValueError as e:
        die(str(e))
    ext = "." + a.format if a.format else None
    ext = {".microdvd": ".sub", ".tmp": ".txt"}.get(ext, ext)
    failed = 0
    for inp in a.inputs:
        if not os.path.isfile(inp):
            sys.stderr.write(f"{PROG}: no such file: {inp}\n")
            failed += 1
            continue
        rep = Report(a.quiet)
        if len(a.inputs) > 1:
            rep.say(f"== {inp}")
        try:
            subs = load_subs(inp, a.encoding, rep)
        except Exception as e:      # pysubs2 raises several types for bad files
            sys.stderr.write(f"{PROG}: cannot read {inp}: {e}\n")
            failed += 1
            continue
        clean(subs, o, rep, rules)
        if a.dry_run:
            continue
        dest = a.output or out_path(inp, a, ext)
        if a.in_place:
            shutil.copy2(inp, inp + ".bak")
        save_subs(subs, dest, a.format)
        rep.say(f"wrote {dest}")
    sys.exit(1 if failed else 0)


def cmd_transcribe(a):
    rep = Report(a.quiet)
    subs = run_whisper(a, a.media, a.language)
    if not a.no_clean:
        try:
            clean(subs, options_from(a), rep)
        except ValueError as e:
            die(str(e))
    dest = a.output or os.path.splitext(a.media)[0] + "." + (a.format or "srt").replace("microdvd", "sub")
    if a.dry_run:
        return
    if os.path.exists(dest) and not a.output:
        die(f"{dest} already exists, pass -o to choose a name")
    save_subs(subs, dest, a.format)
    rep.say(f"wrote {dest}")


def cmd_redo(a):
    if a.end <= a.start:
        die("END must be after START")
    if not os.path.isfile(a.subs):
        die(f"no such file: {a.subs}")
    rep = Report(a.quiet)
    subs = load_subs(a.subs, a.encoding, rep)
    new = run_whisper(a, a.media, a.language, a.start, a.end)
    splice(subs, new, a.start, a.end, rep)
    if not a.no_clean:
        try:
            clean(subs, options_from(a), rep)
        except ValueError as e:
            die(str(e))
    if a.dry_run:
        return
    stem, ext = os.path.splitext(a.subs)
    dest = a.output or (re.sub(r"\.clean$", "", stem) + ".clean" + ext)
    save_subs(subs, dest, a.format)
    rep.say(f"wrote {dest}")


def cmd_patterns(a):
    print(f"user patterns file: {user_patterns_path()}"
          + ("" if os.path.isfile(user_patterns_path()) else " (not present)"))
    print("format: one rule per line, 'drop REGEX' or 'cut REGEX' (add -case for case-sensitive)\n")
    for lang, rules in BUILTIN.items():
        print(f"[{lang}]")
        for r in rules:
            print(f"  {r.kind:4}  {r.label:12}  {r.pattern}")
        print()
    print("[sound tags]")
    print(f"  words: {SOUND_WORDS}")


def main(argv=None):
    p = argparse.ArgumentParser(prog=PROG, description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"{PROG} {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="COMMAND")

    c = sub.add_parser("clean", help="clean subtitle files")
    c.add_argument("inputs", nargs="+", metavar="FILE", help="subtitle files")
    add_output_opts(c)
    add_clean_opts(c)
    c.set_defaults(func=cmd_clean)

    t = sub.add_parser("transcribe", help="make subtitles from a media file with whisper.cpp, then clean")
    t.add_argument("media", help="video or audio file")
    t.add_argument("-l", "--language", default="auto",
                   help="spoken language code, or auto (default: auto)")
    t.add_argument("--no-clean", action="store_true", help="skip the clean pass")
    add_output_opts(t, single=True)
    add_whisper_opts(t)
    add_clean_opts(t)
    t.set_defaults(func=cmd_transcribe)

    r = sub.add_parser("redo", help="re-transcribe a time range and splice it in")
    r.add_argument("subs", help="subtitle file to patch")
    r.add_argument("media", help="the video or audio file it belongs to")
    r.add_argument("start", type=parse_time, help="range start, e.g. 17:26 or 1:01:03.5")
    r.add_argument("end", type=parse_time, help="range end")
    r.add_argument("language", help="forced language code, e.g. de or en")
    r.add_argument("--no-clean", action="store_true", help="splice only, skip the clean pass")
    add_output_opts(r, single=True)
    add_whisper_opts(r)
    add_clean_opts(r)
    r.set_defaults(func=cmd_redo)

    pt = sub.add_parser("patterns", help="list built-in patterns and the user file location")
    pt.set_defaults(func=cmd_patterns)

    a = p.parse_args(argv)
    for name in ("in_place", "out_dir"):
        if not hasattr(a, name):
            setattr(a, name, None)
    try:
        a.func(a)
    except subprocess.CalledProcessError as e:
        die(f"{os.path.basename(e.cmd[0])} failed with exit code {e.returncode}")
    except KeyboardInterrupt:
        die("interrupted", 130)
    except BrokenPipeError:
        # Output piped into head or similar and closed early: not an error.
        sys.stderr.close()
        sys.exit(0)


if __name__ == "__main__":
    main()
