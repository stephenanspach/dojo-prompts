#!/usr/bin/env python3
"""Redact words you already know from a Japanese SRT, leaving a readable sentence.

Goal: glance down while watching and instantly see only the words you have yet to
learn. Grammar and particles stay intact so the sentence still reads; known content
words collapse to ・ so your eye skips them.

Rules
  - Known CONTENT words (noun/verb/adj/adverb/adnominal)  -> ・ (one per char)
  - Unknown content words                                  -> shown
  - Particles, auxiliaries, grammar (は/を/ている/わけ/…)     -> always shown
  - Proper nouns (田中, 埼玉, はるか)                        -> always shown (follow who/where)

"Known" comes straight from AnkiMorphs' own database (lemma-level, matching the
profile's `interval_for_known_morphs`), and text is tokenized with AnkiMorphs' own
bundled MeCab (IPADIC, %f[6] = base form) so lemmas line up exactly with its data.

    python3 redact_known_subs.py input.srt [-o out.srt] [--min-interval 1]
"""
import argparse, os, re, sqlite3, subprocess, sys
from collections import Counter
from pathlib import Path

PROFILE = Path.home() / "Library/Application Support/Anki2/Stephen"
MECAB = Path.home() / "Library/Application Support/Anki2/addons21/1974309724"

# Mirrors AnkiMorphs' mecab_wrapper.py (%f[6] = base form = lemma), plus %ps/%pe byte
# offsets so we can redact by position. String-replacing a surface would corrupt
# substrings of other tokens (e.g. redacting し from する would eat the し in でしょう).
NODE_FMT = "%f[6]\t%m\t%f[0]\t%f[1]\t%ps\t%pe\r"
POS_BLACKLIST = {"記号", "補助記号", "空白"}
CONTENT_POS = {"名詞", "動詞", "形容詞", "副詞", "連体詞"}
# 非自立 = こと/もの/わけ/ている -> grammar, keep visible.
# 接尾 (口/場/的/さん) is NOT skipped: it's a bound part of a compound, and leaving it
# visible strands fragments like 登山口 -> "・・口". Redact it with its stem.
SKIP_SUBPOS = {"非自立"}
PROPER_NOUN = "固有名詞"           # names: always keep visible


def load_known(min_interval: int) -> set[str]:
    con = sqlite3.connect(PROFILE / "ankimorphs.db")
    rows = con.execute(
        "SELECT DISTINCT lemma FROM Morphs WHERE highest_lemma_learning_interval >= ?",
        (min_interval,),
    )
    return {r[0] for r in rows}


def tokenize(text: str):
    """-> [(lemma, surface, pos, sub_pos, byte_start, byte_end)] via AnkiMorphs' MeCab.

    Unknown tokens (latin words, novel spellings) emit no node (--unk-format=), so their
    bytes simply survive in the gaps between tokens and are copied through verbatim.
    """
    env = dict(os.environ, DYLD_FALLBACK_LIBRARY_PATH=str(MECAB))  # bundled libmecab
    p = subprocess.run(
        [str(MECAB / "mecab"), f"--node-format={NODE_FMT}", "--eos-format=\n",
         "--unk-format=", "-d", str(MECAB), "-r", str(MECAB / "mecabrc")],
        input=text.encode("utf-8"), capture_output=True, env=env)
    out = []
    for chunk in p.stdout.decode("utf-8", "ignore").split("\r"):
        parts = chunk.split("\t")
        if len(parts) < 6:
            continue
        lemma, surface, pos, sub, ps, pe = (x.strip() for x in parts[:6])
        if not lemma or not surface or pos in POS_BLACKLIST:
            continue
        try:
            out.append((lemma, surface, pos, sub, int(ps), int(pe)))
        except ValueError:
            continue
    return out


def redactable(pos: str, sub: str) -> bool:
    """A real vocabulary word (not grammar, not a name)."""
    return pos in CONTENT_POS and sub not in SKIP_SUBPOS and sub != PROPER_NOUN


def redact_line(line: str, known: set[str], stats: Counter, unknown: Counter) -> str:
    raw = line.encode("utf-8")
    spans = []
    for lemma, surface, pos, sub, ps, pe in tokenize(line):
        if not redactable(pos, sub):
            continue
        stats["content"] += 1
        if lemma in known:
            stats["known"] += 1
            spans.append((ps, pe, "・" * len(surface)))
        else:
            stats["unknown"] += 1
            unknown[lemma] += 1
    if not spans:
        return line
    spans.sort()
    out, cursor = bytearray(), 0
    for ps, pe, dots in spans:
        out += raw[cursor:ps]          # everything between tokens survives untouched
        out += dots.encode("utf-8")
        cursor = pe
    out += raw[cursor:]
    return out.decode("utf-8", "ignore")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("srt")
    ap.add_argument("-o", "--out")
    ap.add_argument("--min-interval", type=int, default=1,
                    help="known threshold; 1 = your AnkiMorphs setting (default)")
    a = ap.parse_args()

    src = Path(a.srt)
    dst = Path(a.out) if a.out else src.with_suffix(".redacted.srt")
    known = load_known(a.min_interval)

    stats, unknown = Counter(), Counter()
    out_lines = []
    for raw in src.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        # keep index + timing lines + blanks verbatim
        if not s or "-->" in s or re.fullmatch(r"\d+", s):
            out_lines.append(raw)
        else:
            out_lines.append(redact_line(raw, known, stats, unknown))
    dst.write_text("\n".join(out_lines) + "\n", encoding="utf-8")

    c = stats["content"] or 1
    print(f"known lemmas loaded : {len(known)} (interval >= {a.min_interval})")
    print(f"content words       : {stats['content']}")
    print(f"  known -> redacted : {stats['known']} ({100*stats['known']/c:.0f}%)")
    print(f"  UNKNOWN -> shown  : {stats['unknown']} ({100*stats['unknown']/c:.0f}%)")
    print(f"distinct unknown    : {len(unknown)}")
    if unknown:
        print("top unknowns        : " + ", ".join(w for w, _ in unknown.most_common(25)))
    print(f"\nwrote {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
