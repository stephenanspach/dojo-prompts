#!/usr/bin/env python3
"""
Sync WaniKani Guru+ items to Anki as manually-known words.

Usage:
    WANIKANI_API_KEY=<key> python3 wanikani_sync.py
    WANIKANI_API_KEY=<key> python3 wanikani_sync.py --full   # ignore last-sync timestamp

Adds one 🇯🇵 MvJ note per Guru+ kanji/vocabulary item, tagged
_card-status::i+0-manually with the character in the Word field.
State (last-sync timestamp + seen subject IDs) is stored in
tracker/wanikani_sync_state.json next to this repo root.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# ── Config ────────────────────────────────────────────────────────────────────
WANIKANI_BASE = "https://api.wanikani.com/v2"
ANKICONNECT_URL = "http://localhost:8765"
DECK_NAME = "Ankimorphs database::WaniKani Known"
NOTE_TYPE = "🇯🇵 MvJ"
KNOWN_TAG = "_card-status::i+0-manually"
# SRS stages: 5=Guru1, 6=Guru2, 7=Master, 8=Enlightened, 9=Burned
GURU_PLUS_STAGES = "5,6,7,8,9"
# Vocabulary only — skip kanji (single characters, not words)
SUBJECT_TYPES = "vocabulary,kana_vocabulary"

# State file lives alongside tracker/
SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent.parent
STATE_FILE = REPO_ROOT / "tracker" / "wanikani_sync_state.json"
# API key fallback file (used when WANIKANI_API_KEY env var is unset)
KEY_FILE = SCRIPT_DIR / ".wanikani_api_key"


def get_api_key() -> str:
    """Read the WaniKani API key from the env var, falling back to KEY_FILE."""
    key = os.environ.get("WANIKANI_API_KEY", "").strip()
    if not key and KEY_FILE.exists():
        key = KEY_FILE.read_text().strip()
    return key


# ── WaniKani helpers ──────────────────────────────────────────────────────────
def wk_get_all(url: str, api_key: str) -> list:
    """Fetch all pages from a WaniKani API endpoint."""
    headers = {"Authorization": f"Bearer {api_key}", "Wanikani-Revision": "20170710"}
    results = []
    while url:
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 60))
            print(f"  Rate limited — waiting {retry_after}s...")
            time.sleep(retry_after)
            continue
        resp.raise_for_status()
        body = resp.json()
        results.extend(body.get("data", []))
        url = body.get("pages", {}).get("next_url")
        if url:
            time.sleep(0.25)  # be polite between pages
    return results


def fetch_guru_plus_assignments(api_key: str, updated_after: str | None = None) -> list:
    url = f"{WANIKANI_BASE}/assignments?srs_stages={GURU_PLUS_STAGES}&subject_types={SUBJECT_TYPES}"
    if updated_after:
        url += f"&updated_after={updated_after}"
    return wk_get_all(url, api_key)


def fetch_subjects(subject_ids: list[int], api_key: str) -> dict[int, dict]:
    """Fetch subject objects by ID, returning {id: subject_data} dict."""
    subjects = {}
    for i in range(0, len(subject_ids), 500):
        batch = subject_ids[i : i + 500]
        ids_param = ",".join(str(x) for x in batch)
        url = f"{WANIKANI_BASE}/subjects?ids={ids_param}"
        items = wk_get_all(url, api_key)
        for item in items:
            subjects[item["id"]] = item
        if i + 500 < len(subject_ids):
            time.sleep(0.25)
    return subjects


# ── AnkiConnect helpers ───────────────────────────────────────────────────────
def anki(action: str, **params):
    payload = {"action": action, "version": 6, "params": params}
    resp = requests.post(ANKICONNECT_URL, json=payload, timeout=10)
    body = resp.json()
    if body.get("error"):
        raise RuntimeError(f"AnkiConnect [{action}]: {body['error']}")
    return body["result"]


def wait_for_anki(timeout: float = 45.0, interval: float = 3.0) -> bool:
    """Poll AnkiConnect until it responds or timeout elapses."""
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
    """Return set of Word values already tagged as known in Anki."""
    note_ids = anki("findNotes", query=f'note:"{NOTE_TYPE}" tag:"{KNOWN_TAG}"')
    if not note_ids:
        return set()
    notes = anki("notesInfo", notes=note_ids)
    return {n["fields"]["Word"]["value"] for n in notes if n["fields"]["Word"]["value"]}


# ── State management ──────────────────────────────────────────────────────────
def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"last_sync": None, "synced_subject_ids": []}


def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    full_sync = "--full" in sys.argv

    api_key = get_api_key()
    if not api_key:
        print("Error: no WaniKani API key found.")
        print(f"  Set WANIKANI_API_KEY, or put the key in {KEY_FILE}")
        sys.exit(1)

    # Wait briefly for AnkiConnect — on Anki launch, prefs21.db (our trigger) can
    # be written before the AnkiConnect add-on starts listening. exit 0 on timeout
    # so scheduled runs don't flag a hard failure.
    if not wait_for_anki():
        print(f"Anki not reachable at {ANKICONNECT_URL} after waiting — is Anki open?")
        sys.exit(0)

    state = load_state()
    updated_after = None if full_sync else state.get("last_sync")
    synced_ids: set[int] = set(state.get("synced_subject_ids", []))

    if updated_after:
        print(f"Incremental sync — fetching items updated after {updated_after}")
    else:
        print("Full sync — fetching all Guru+ items")

    # Record sync start time before fetching (so we don't miss items updated during the run)
    sync_start = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    print("Fetching assignments from WaniKani...")
    assignments = fetch_guru_plus_assignments(api_key, updated_after)
    print(f"  {len(assignments)} assignment(s) returned")

    # Only process newly seen subjects
    new_assignments = [a for a in assignments if a["data"]["subject_id"] not in synced_ids]
    if not new_assignments:
        print("No new Guru+ items since last sync.")
        state["last_sync"] = sync_start
        save_state(state)
        return

    subject_ids = [a["data"]["subject_id"] for a in new_assignments]
    print(f"Fetching {len(subject_ids)} subject(s)...")
    subjects = fetch_subjects(subject_ids, api_key)

    # Build notes to add, skipping anything already in Anki
    print("Checking existing Anki known-word notes...")
    known_words = existing_known_words()
    print(f"  {len(known_words)} word(s) already marked known in Anki")

    notes_to_add = []
    chars_seen_this_run: set[str] = set()

    for assignment in new_assignments:
        sid = assignment["data"]["subject_id"]
        subject = subjects.get(sid)
        if not subject:
            continue

        characters = subject["data"].get("characters")
        if not characters:
            continue  # some radicals have no character

        if characters in known_words or characters in chars_seen_this_run:
            synced_ids.add(sid)
            continue

        # Primary English meaning, if available
        meanings = subject["data"].get("meanings", [])
        primary = next((m["meaning"] for m in meanings if m.get("primary")), "")
        if not primary and meanings:
            primary = meanings[0]["meaning"]

        notes_to_add.append({
            "deckName": DECK_NAME,
            "modelName": NOTE_TYPE,
            # Sentence is the first field and cannot be empty; am-study-morphs is
            # the field AnkiMorphs reads to mark the word known.
            "fields": {
                "Sentence": characters,
                "Word": characters,
                "am-study-morphs": characters,
                "Definition": primary,
            },
            "tags": [KNOWN_TAG],
            # We dedup against existing known notes ourselves (see known_words);
            # allow duplicates so a stray first-field collision elsewhere in the
            # collection doesn't block adding the known-word marker.
            "options": {"allowDuplicate": True},
        })
        chars_seen_this_run.add(characters)
        synced_ids.add(sid)

    if not notes_to_add:
        print("All new items are already marked known in Anki.")
        state["last_sync"] = sync_start
        state["synced_subject_ids"] = sorted(synced_ids)
        save_state(state)
        return

    # Ensure deck exists
    anki("createDeck", deck=DECK_NAME)

    # Add notes in batches of 100
    print(f"Adding {len(notes_to_add)} note(s) to Anki...")
    added = 0
    failed = 0
    for i in range(0, len(notes_to_add), 100):
        batch = notes_to_add[i : i + 100]
        results = anki("addNotes", notes=batch)
        added += sum(1 for r in results if r is not None)
        failed += sum(1 for r in results if r is None)

    print(f"\nDone.")
    print(f"  Added:   {added}")
    if failed:
        print(f"  Skipped (duplicate in collection): {failed}")

    state["last_sync"] = sync_start
    state["synced_subject_ids"] = sorted(synced_ids)
    save_state(state)
    print(f"State saved to {STATE_FILE}")


if __name__ == "__main__":
    main()
