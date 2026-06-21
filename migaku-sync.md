---
name: migaku-sync
description: |
  Sync Migaku "known" words into Anki as manually-known words, so AnkiMorphs
  treats them as known. Reads Migaku's data directly out of Chrome's IndexedDB.
allowed-tools:
  - Bash
  - Read
  - Edit
---

# Migaku → Anki Known-Words Sync

Pulls every word Migaku marks as **KNOWN** and creates a `🇯🇵 MvJ` note for each
in Anki, tagged `_card-status::i+0-manually` so the AnkiMorphs setup recognizes
them as known words. Sibling of the WaniKani sync — same note type, same tag,
into deck **`Ankimorphs database::Migaku Known`**.

## How the data is obtained (no public API)

Migaku has no public API. The browser extension at `study.migaku.com` keeps its
SRS state in **Chrome's IndexedDB**, in a database named `srs`, object store
`data`. The value is a **gzip-compressed SQLite database** stored as an external
blob. The script:

1. Copies Chrome's IndexedDB leveldb + blob dirs to a temp folder.
2. Decodes the IndexedDB record with `ccl_chromium_reader`, gunzips the value to
   recover the SQLite file (`core_*.db`).
3. Queries `WordList` for `language='ja' AND knownStatus='KNOWN' AND del=0` and
   takes the distinct `dictForm` values.

Paths (Chrome **Default** profile):
`~/Library/Application Support/Google/Chrome/Default/IndexedDB/https_study.migaku.com_0.indexeddb.{leveldb,blob}`

> Note: the leveldb log sometimes references a superseded blob filename (stale
> pointer). The script falls back to the largest blob file in the store dir,
> which is the current SQLite snapshot.

## Automatic sync on Anki launch

A launchd agent runs this sync **whenever Anki launches**, via `WatchPaths` on
`~/Library/Application Support/Anki2/prefs21.db` (Anki writes it on startup) —
the same trigger the WaniKani sync uses. The script reads Chrome's IndexedDB
**live** (no need to quit Chrome); the stale-blob fallback handles a mid-write
database. Worst case a run reads a slightly stale snapshot or is skipped, and the
next Anki launch catches up.

- Agent: `~/Library/LaunchAgents/com.mattvsjapan.migaku-sync.plist`
- Log: `tracker/migaku_sync.log`
- On launch, the script waits up to ~45s for AnkiConnect to come up (the
  `prefs21.db` trigger can fire before the add-on starts listening).

```bash
launchctl list | grep migaku                                  # is it loaded?
launchctl start com.mattvsjapan.migaku-sync                   # run now
launchctl unload ~/Library/LaunchAgents/com.mattvsjapan.migaku-sync.plist  # disable
launchctl load   ~/Library/LaunchAgents/com.mattvsjapan.migaku-sync.plist  # re-enable
```

> Why not a timed cron like WaniKani? Migaku has no API; this reads Chrome's
> local IndexedDB. The in-browser read was abandoned because the
> `study.migaku.com` SPA freezes the page thread and the JS bridge times out.
> Tying the sync to Anki launch is the reliable hands-off option.

## Prerequisites

- `ccl_chromium_reader`: `python3.14 -m pip install --break-system-packages git+https://github.com/cclgroupltd/ccl_chromium_reader.git`
- `requests`.
- **Anki open** (AnkiConnect at `localhost:8765`).
- Chrome may be open or closed. For a manual run where you want the most
  consistent possible read, quitting Chrome (Cmd+Q) first guarantees the
  database isn't mid-write — but it's optional.

## Run it

```bash
cd "/Users/spach/Library/Mobile Documents/com~apple~CloudDocs/Japanese/mattvsjapan"
python3.14 dojo-prompts/scripts/migaku_sync.py          # sync into Anki
python3.14 dojo-prompts/scripts/migaku_sync.py --dump   # just print known words, no Anki writes
python3.14 dojo-prompts/scripts/migaku_sync.py --lang ja # language filter (default ja)
```

## What it writes

For each new known word, a `🇯🇵 MvJ` note in `Ankimorphs database::Migaku Known`
with the word in `Sentence` (required first field), `Word`, and `am-study-morphs`
(the field AnkiMorphs reads), tagged `_card-status::i+0-manually`. Words already
marked known anywhere in Anki (e.g. from the WaniKani sync) are skipped.

## State

`tracker/migaku_sync_state.json` records `last_sync` and the set of words seen.
Re-runs are idempotent — already-added words are never duplicated.

Initial sync (2026-06-15): 2141 distinct known JA words → 1160 new notes added
(the rest were already known via WaniKani / existing cards).
