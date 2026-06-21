---
name: wanikani-sync
description: |
  Sync Guru+ vocabulary from WaniKani into Anki as manually-known words, so
  AnkiMorphs treats them as known. Idempotent and incremental.
allowed-tools:
  - Bash
  - Read
  - Edit
---

# WaniKani → Anki Known-Words Sync

Pulls every **Guru or higher** vocabulary item from the WaniKani API and creates
a `🇯🇵 MvJ` note for each in Anki, tagged `_card-status::i+0-manually` so the
AnkiMorphs setup recognizes them as known words.

## Prerequisites

- **Anki must be open** (the [AnkiConnect](https://foosoft.net/projects/anki-connect/)
  add-on serves the API at `http://localhost:8765`).
- `requests` Python package (`python3.14 -m pip install requests --break-system-packages`).
- A WaniKani API key. The script reads it from the `WANIKANI_API_KEY` env var,
  or falls back to the file `dojo-prompts/scripts/.wanikani_api_key`
  (chmod 600; not meant to be shared). Get/regenerate a key at
  https://www.wanikani.com/settings/personal_access_tokens — read-only is enough.

## Run it

```bash
cd "/Users/spach/Library/Mobile Documents/com~apple~CloudDocs/Japanese/mattvsjapan"
python3.14 dojo-prompts/scripts/wanikani_sync.py          # incremental (normal)
python3.14 dojo-prompts/scripts/wanikani_sync.py --full   # re-check everything
```

## What it does

- Fetches assignments at SRS stages 5–9 (Guru1 → Burned), subject types
  `vocabulary` and `kana_vocabulary` only — **kanji are skipped** (single
  characters, not words).
- For each new item, adds a `🇯🇵 MvJ` note to deck
  **`Ankimorphs database::WaniKani Known`** with the word in the `Sentence`,
  `Word`, and `am-study-morphs` fields (Sentence is the note type's first field
  and can't be empty; `am-study-morphs` is the field AnkiMorphs reads), the
  English meaning in `Definition`, and tag `_card-status::i+0-manually`.
- Skips any word already marked known in Anki, and dedups within the run.

## Incremental state

State lives in `tracker/wanikani_sync_state.json`:
- `last_sync` — ISO timestamp; re-runs only fetch items updated after it
  (WaniKani `updated_after`).
- `synced_subject_ids` — every WaniKani subject ID already processed.

Delete this file (or use `--full`) to force a complete re-sync. Re-runs are
idempotent — already-added words are never duplicated.

## Automatic sync on Anki launch

A launchd agent runs the sync **whenever Anki launches**. It does this via
`WatchPaths` on `~/Library/Application Support/Anki2/prefs21.db`, which Anki
writes on startup. `ThrottleInterval` (60s) prevents rapid re-fires. Because the
sync is incremental and idempotent, an extra trigger (e.g. on Anki shutdown,
which also touches the file) just no-ops.

- Agent: `~/Library/LaunchAgents/com.mattvsjapan.wanikani-sync.plist`
- Log: `tracker/wanikani_sync.log`

Manage it:
```bash
launchctl list | grep wanikani                                   # is it loaded?
launchctl start com.mattvsjapan.wanikani-sync                    # run now
launchctl unload ~/Library/LaunchAgents/com.mattvsjapan.wanikani-sync.plist  # disable
launchctl load   ~/Library/LaunchAgents/com.mattvsjapan.wanikani-sync.plist  # re-enable
```
