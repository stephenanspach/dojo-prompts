#!/usr/bin/env python3
"""Remove English-speech runs from a Japanese transcript JSON (in place; original kept as .orig.json).

STT run with language=ja renders English narration as unspaced Latin fragments
("I'mTakashifromJapan"). Those make junk subtitle lines and Anki cards. This drops
contiguous runs of Latin-script tokens containing >= MIN_LETTERS letters, and keeps
short Latin words (AI, USA, iPhone) that occur inside Japanese speech.

Usage: python3 strip_english.py <transcript.json> [MIN_LETTERS=8]
"""
import json, re, shutil, sys

path = sys.argv[1]
min_letters = int(sys.argv[2]) if len(sys.argv) > 2 else 8
d = json.load(open(path))
words = d["words"]
CJK = re.compile(r"[぀-ヿ㐀-鿿]")
LAT = re.compile(r"[A-Za-z]")

def is_latin(w):
    t = w["text"]
    if CJK.search(t):
        return False
    return bool(LAT.search(t)) or (t.strip() == "" or re.fullmatch(r"[\s'.,?!\-]+", t) is not None)

drop = set()
i = 0
while i < len(words):
    if is_latin(words[i]) and LAT.search(words[i]["text"]):
        j = i
        while j < len(words) and is_latin(words[j]):
            j += 1
        run = words[i:j]
        if sum(len(LAT.findall(w["text"])) for w in run) >= min_letters:
            drop.update(range(i, j))
        i = j
    else:
        i += 1

kept = [w for k, w in enumerate(words) if k not in drop]
shutil.copy(path, path.replace(".json", ".orig.json"))
d["words"] = kept
d["text"] = "".join(w["text"] for w in kept)
json.dump(d, open(path, "w"), ensure_ascii=False, indent=1)
print(f"dropped {len(drop)} of {len(words)} tokens ({len(kept)} kept)")
