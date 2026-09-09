#!/usr/bin/env python3
"""Smooth ElevenLabs TTS clips so they don't start/end abruptly.

ElevenLabs returns audio trimmed flush to the waveform (zero silence buffer), so
short word clips begin/end on a hard edge that sounds clipped/clicky. This adds a
short fade + a little silence at each end.

Agreed defaults (2026-07, tuned by ear on もののきてん):
  fade-in 15ms · lead silence 120ms · fade-out 80ms · trailing silence 150ms

Use as a library after any TTS write:
    from smooth_audio import smooth_clip
    smooth_clip(path)                 # smooths in place

Or as a one-time batch over Anki media (skips already-smoothed clips):
    python3 smooth_audio.py "bsy_*.mp3" "jfood_*.mp3"
"""
import base64, json, subprocess, sys, tempfile, urllib.request
from pathlib import Path

FADE_IN, LEAD, FADE_OUT, TRAIL = 0.015, 0.120, 0.080, 0.150


def _dur(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nk=1:nw=1", str(path)], capture_output=True, text=True)
    return float(out.stdout.strip())


def has_lead_silence(path, min_ms=80):
    """True if the clip already begins with >= min_ms of silence (already smoothed)."""
    # NB: silencedetect logs at ffmpeg's *info* level, so do NOT pass -v error here
    # (that would hide the silence_start/duration lines we parse).
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
                        "-af", "silencedetect=noise=-45dB:d=0.03", "-f", "null", "-"],
                       capture_output=True, text=True)
    start0 = dur = None
    for line in r.stderr.splitlines():
        if "silence_start:" in line:
            start0 = float(line.split("silence_start:")[1].strip())
        if "silence_duration:" in line and start0 is not None and start0 < 0.02:
            dur = float(line.split("silence_duration:")[1].strip())
            break
    return dur is not None and dur * 1000 >= min_ms


def smooth_clip(src, dst=None, fade_in=FADE_IN, lead=LEAD, fade_out=FADE_OUT, trail=TRAIL):
    """Apply fade+pad. dst defaults to in-place. Returns dst path."""
    src = Path(src)
    dst = Path(dst) if dst else src
    d = _dur(src)
    fo = min(fade_out, d * 0.5)
    fo_st = max(0.0, d - fo)
    af = (f"afade=t=in:st=0:d={fade_in},afade=t=out:st={fo_st:.4f}:d={fo},"
          f"adelay={int(lead*1000)}:all=1,apad=pad_dur={trail}")
    tmp = Path(tempfile.mkstemp(suffix=".mp3")[1])
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-af", af,
                    "-c:a", "libmp3lame", "-q:a", "4", str(tmp)], check=True)
    tmp.replace(dst)
    return dst


# ---------- one-time Anki batch ----------
def _call(action, params=None):
    p = {"action": action, "version": 6}
    if params is not None:
        p["params"] = params
    d = json.load(urllib.request.urlopen("http://localhost:8765", json.dumps(p).encode()))
    if d.get("error"):
        raise SystemExit(f"AnkiConnect {action}: {d['error']}")
    return d["result"]


def batch(patterns):
    names = []
    for pat in patterns:
        names += _call("getMediaFilesNames", {"pattern": pat})
    names = sorted(set(names))
    print(f"{len(names)} file(s) matched {patterns}")
    smoothed = skipped = 0
    for i, name in enumerate(names, 1):
        b64 = _call("retrieveMediaFile", {"filename": name})
        if not b64:
            continue
        tmp = Path(tempfile.mkstemp(suffix=".mp3")[1])
        tmp.write_bytes(base64.b64decode(b64))
        if has_lead_silence(tmp):
            skipped += 1
            tmp.unlink(missing_ok=True)
            continue
        smooth_clip(tmp)
        _call("storeMediaFile", {"filename": name, "data": base64.b64encode(tmp.read_bytes()).decode()})
        tmp.unlink(missing_ok=True)
        smoothed += 1
        if smoothed % 50 == 0:
            print(f"  [{i}/{len(names)}] smoothed {smoothed}, skipped {skipped}")
    print(f"DONE. smoothed {smoothed}, skipped {skipped} (already smooth).")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: smooth_audio.py <anki-media-glob> [more globs...]")
    batch(sys.argv[1:])
