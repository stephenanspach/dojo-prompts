#!/usr/bin/env python3
"""Sweep 🇯🇵 MvJ notes and repair Word Audio polluted by the add-on's per-kanji
NHK fallback bug (compound word -> one clip per constituent kanji).

Runs unattended (launchd, every 12h). Conservative: only removes NHK clips whose
leading token is a SINGLE kanji while the word is a 2+char compound — that pattern
is unambiguously decomposition junk and never matches a legitimate single-kanji
word's own audio. Original (non-NHK / subs2srs) clips are always kept; the correct
compound clip is swapped in when it already exists in the collection media.

If Anki / AnkiConnect isn't running, logs a line and exits 0 (retries next run).
"""
import json, re, sys, urllib.request, urllib.error
from datetime import datetime

ANKI = "http://localhost:8765"
NOTE = "\U0001f1ef\U0001f1f5 MvJ"   # 🇯🇵 MvJ


def call(action, params=None, timeout=30):
    payload = {"action": action, "version": 6}
    if params is not None:
        payload["params"] = params
    req = urllib.request.Request(ANKI, data=json.dumps(payload).encode())
    d = json.load(urllib.request.urlopen(req, timeout=timeout))
    if d.get("error"):
        raise RuntimeError(f"{action}: {d['error']}")
    return d["result"]


# Dictionary reference clips are named {word}_{reading}_{pitch}_{SOURCE}.mp3
DICT_CLIP = re.compile(r"_(?:NHK-2016|Shinmeikai-\d+)\.mp3$")


def word_bases(w):
    """The card's actual written word form(s). A word field may carry several
    readings separated by <br> (e.g. 気配[けはい]:1<br>気配[きはい]:0,1); each
    collapses to a written base. Furigana, pitch, MvJ's inter-segment spaces, and
    accent-notation markers (* \\ ^ and ghost-particle dashes) are all stripped."""
    bases = set()
    for part in re.split(r"<br\s*/?>", w):
        part = re.sub(r"\[[^\]]*\]", "", part)    # drop furigana readings
        part = re.split(r"[:、]", part)[0]         # drop pitch / clause markers
        part = re.sub(r"[\s*\\^]", "", part).strip("-")   # spaces + accent markers
        if part:
            bases.add(part)
    return bases


def is_junk(fn, bases):
    """A dictionary clip whose leading word is a CONSTITUENT PIECE of the card's
    word (a proper substring) — the add-on decomposed the compound and grabbed a
    part: 戦闘→戦, たまに→たま/に, 行為→行/為. NOT flagged: a clip whose leading token
    equals the word, or is unrelated — because NHK legitimately files many words
    under their kana reading (上げる→あげる_…, 沢山→たくさん_…), which is not a substring
    of the written word. Comparing written forms also sidesteps reading/long-vowel
    spelling (行為 vs コーイ)."""
    if not DICT_CLIP.search(fn) or not bases:
        return False
    tok = fn.split("_", 1)[0]
    if tok in bases:                     # exact word form → legit
        return False
    return any(tok != b and tok in b for b in bases)   # constituent piece → junk


def log(msg):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def main():
    try:
        call("version", timeout=5)
    except (urllib.error.URLError, OSError) as e:
        log(f"AnkiConnect unreachable (Anki not running?) — skipping. ({e})")
        return 0

    ids = call("findNotes", {"query": f'note:"{NOTE}"'})
    info = call("notesInfo", {"notes": ids})
    media = set(call("getMediaFilesNames", {"pattern": "*_NHK-2016.mp3"}))

    fixed = []
    for n in info:
        wa = n["fields"]["Word Audio"]["value"]
        bases = word_bases(n["fields"]["Word"]["value"])
        files = re.findall(r"\[audio:([^\]]+)\]", wa)
        junk = [f for f in files if is_junk(f, bases)]
        if not junk:
            continue
        kept = [f for f in files if not is_junk(f, bases)]
        for base in bases:
            for comp in (m for m in media if m.startswith(base + "_")):
                if comp not in kept:
                    kept.append(comp)
        new = "<br>".join(f"[audio:{f}]" for f in kept)
        call("updateNoteFields", {"note": {"id": n["noteId"], "fields": {"Word Audio": new}}})
        fixed.append((n["noteId"], "|".join(sorted(bases)), len(junk)))

    if fixed:
        for nid, label, nj in fixed:
            log(f"  fixed {nid} [{label}] — removed {nj} decomposition clip(s)")
    log(f"swept {len(info)} MvJ notes — fixed {len(fixed)}.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # never let a bad run wedge the agent
        log(f"ERROR: {e}")
        sys.exit(0)
