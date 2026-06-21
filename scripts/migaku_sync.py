#!/usr/bin/env python3
"""
Sync Migaku "known" words into Anki as manually-known words.

Migaku (the browser extension at study.migaku.com) stores its SRS state in
Chrome's IndexedDB as a gzip-compressed SQLite database. This script reads that
database directly (offline — no browser automation), pulls every word whose
knownStatus is KNOWN, and creates one 🇯🇵 MvJ note per word in Anki, tagged
_card-status::i+0-manually so AnkiMorphs treats them as known.

Usage:
    python3.14 migaku_sync.py            # sync new known words into Anki
    python3.14 migaku_sync.py --dump     # just print the known-word count and exit
    python3.14 migaku_sync.py --lang ja  # language filter (default: ja)

Requires: ccl_chromium_reader, requests. Anki must be open (AnkiConnect).
For the most consistent read, quit Chrome first — the script works with Chrome
open too, but a live database can occasionally be mid-write.
"""

import argparse
import atexit
import gzip
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

import requests
from ccl_chromium_reader import ccl_chromium_indexeddb as idb

# ── Config ────────────────────────────────────────────────────────────────────
ANKICONNECT_URL = "http://localhost:8765"
DECK_NAME = "Ankimorphs database::Migaku Known"
NOTE_TYPE = "🇯🇵 MvJ"
KNOWN_TAG = "_card-status::i+0-manually"

CHROME_IDB = (
    Path.home()
    / "Library/Application Support/Google/Chrome/Default/IndexedDB"
)
LEVELDB_DIR = CHROME_IDB / "https_study.migaku.com_0.indexeddb.leveldb"
BLOB_DIR = CHROME_IDB / "https_study.migaku.com_0.indexeddb.blob"

SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent.parent
STATE_FILE = REPO_ROOT / "tracker" / "migaku_sync_state.json"


# ── Extract the Migaku SQLite DB from Chrome's IndexedDB ────────────────────────
def _install_missing_blob_fallback(blob_root: Path):
    """
    Migaku stores the whole SQLite DB as a single external blob. The leveldb log
    can reference a blob filename that has been superseded on disk (stale pointer,
    common when Chrome is/was live). When the exact blob file is missing, fall
    back to the largest blob file present under the store directory.
    """
    _orig = idb.IndexedDb.get_blob

    def patched(self, db_id, store_id, raw_key, file_index):
        try:
            return _orig(self, db_id, store_id, raw_key, file_index)
        except FileNotFoundError:
            store_dir = blob_root / str(db_id)
            candidates = [p for p in store_dir.rglob("*") if p.is_file()]
            if not candidates:
                raise
            biggest = max(candidates, key=lambda p: p.stat().st_size)
            return open(biggest, "rb")

    idb.IndexedDb.get_blob = patched


def extract_migaku_sqlite() -> Path:
    """Copy Chrome's Migaku IndexedDB to temp, decode it, and write out the
    decompressed SQLite database. Returns the path to the .db file."""
    if not LEVELDB_DIR.exists():
        sys.exit(f"Error: Migaku IndexedDB not found at {LEVELDB_DIR}\n"
                 f"  (Is Migaku set up in Chrome's Default profile?)")

    tmp = Path(tempfile.mkdtemp(prefix="migaku_idb_"))
    atexit.register(lambda: shutil.rmtree(tmp, ignore_errors=True))
    ldb = tmp / "leveldb"
    blob = tmp / "blob"
    shutil.copytree(LEVELDB_DIR, ldb)
    if BLOB_DIR.exists():
        shutil.copytree(BLOB_DIR, blob)

    _install_missing_blob_fallback(blob)

    wrapper = idb.WrappedIndexDB(str(ldb), str(blob))
    store = wrapper["srs"]["data"]

    for rec in store.iterate_records(live_only=False):
        try:
            value = rec.value
        except Exception:
            continue
        if not isinstance(value, dict) or "data" not in value:
            continue
        raw = gzip.decompress(bytes(value["data"]))
        if raw[:15] != b"SQLite format 3":
            continue
        out = tmp / "migaku_core.db"
        out.write_bytes(raw)
        return out

    sys.exit("Error: could not find/decode the Migaku SQLite DB in IndexedDB.")


def known_words(db_path: Path, lang: str) -> list[str]:
    con = sqlite3.connect(db_path)
    rows = con.execute(
        "SELECT dictForm FROM WordList "
        "WHERE language=? AND knownStatus='KNOWN' AND del=0 AND dictForm<>'' "
        "ORDER BY created",
        (lang,),
    ).fetchall()
    con.close()
    # de-dup preserving order
    seen, out = set(), []
    for (w,) in rows:
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out


# ── AnkiConnect helpers ─────────────────────────────────────────────────────────
def anki(action: str, **params):
    resp = requests.post(
        ANKICONNECT_URL,
        json={"action": action, "version": 6, "params": params},
        timeout=15,
    )
    body = resp.json()
    if body.get("error"):
        raise RuntimeError(f"AnkiConnect [{action}]: {body['error']}")
    return body["result"]


def wait_for_anki(timeout: float = 45.0, interval: float = 3.0) -> bool:
    """Poll AnkiConnect until it responds or timeout elapses."""
    import time
    deadline = time.monotonic() + timeout
    while True:
        try:
            anki("version")
            return True
        except Exception:
            if time.monotonic() >= deadline:
                return False
            time.sleep(interval)


def existing_known_words() -> set[str]:
    note_ids = anki("findNotes", query=f'note:"{NOTE_TYPE}" tag:"{KNOWN_TAG}"')
    if not note_ids:
        return set()
    notes = anki("notesInfo", notes=note_ids)
    return {n["fields"]["Word"]["value"] for n in notes if n["fields"]["Word"]["value"]}


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"last_sync": None, "synced_words": []}


def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


# ── Main ─────────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", default="ja", help="Migaku language code (default: ja)")
    ap.add_argument("--dump", action="store_true", help="print known-word count and exit")
    args = ap.parse_args()

    print("Reading Migaku database from Chrome's IndexedDB...")
    db_path = extract_migaku_sqlite()
    words = known_words(db_path, args.lang)
    print(f"  {len(words)} known '{args.lang}' word(s) in Migaku")

    if args.dump:
        for w in words:
            print(w)
        return

    # Wait briefly for AnkiConnect — on Anki launch, prefs21.db (our trigger) can
    # be written before the AnkiConnect add-on starts listening.
    if not wait_for_anki():
        print(f"Anki not reachable at {ANKICONNECT_URL} after waiting — is Anki open?")
        sys.exit(0)

    print("Checking existing Anki known-word notes...")
    already_known = existing_known_words()
    print(f"  {len(already_known)} word(s) already marked known in Anki")

    new_words = [w for w in words if w not in already_known]
    if not new_words:
        print("No new Migaku known words to add.")
        from datetime import datetime, timezone
        state = load_state()
        state["last_sync"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        state["synced_words"] = sorted(set(state.get("synced_words", [])) | set(words))
        save_state(state)
        return

    anki("createDeck", deck=DECK_NAME)

    notes = [{
        "deckName": DECK_NAME,
        "modelName": NOTE_TYPE,
        # Sentence is the required first field; am-study-morphs is what AnkiMorphs reads.
        "fields": {"Sentence": w, "Word": w, "am-study-morphs": w},
        "tags": [KNOWN_TAG],
        "options": {"allowDuplicate": True},
    } for w in new_words]

    print(f"Adding {len(notes)} note(s) to Anki...")
    added = 0
    for i in range(0, len(notes), 100):
        results = anki("addNotes", notes=notes[i:i + 100])
        added += sum(1 for r in results if r is not None)

    print(f"\nDone. Added: {added}")

    from datetime import datetime, timezone
    state = load_state()
    state["last_sync"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    state["synced_words"] = sorted(set(state.get("synced_words", [])) | set(words))
    save_state(state)
    print(f"State saved to {STATE_FILE}")


if __name__ == "__main__":
    main()
