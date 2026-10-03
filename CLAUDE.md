# Dojo Prompts

This project contains AI skills for immersion-based Japanese learning. The skill files are located in the `dojo-prompts/` folder (the cloned repo).

## Skills

When the user asks about any of the following, read the corresponding skill file and follow its instructions:

| User says something like... | Skill file |
|---|---|
| "discover content", "find something to watch", "help me find content" | `dojo-prompts/content-discovery.md` |
| "process this video", "process and transcribe", "process content" | `dojo-prompts/process-content.md` |
| "create subtitles", "transcribe this", "make an SRT", "generate subs" | `dojo-prompts/create-srt.md` |
| "translate subtitles", "translate this SRT", "make English subs" | `dojo-prompts/translate-srt.md` |
| "make an Anki deck", "subs2srs", "create flashcards" | `dojo-prompts/anki.md` |
| "style guide", "language parent", "analyze their speech" | `dojo-prompts/style-guide.md` |
| "find my mistakes", "analyze my output", "what am I doing wrong" | `dojo-prompts/find-mistakes.md` |
| "condensed audio", "condense this", "passive listening" | `dojo-prompts/condensed-audio.md` |
| "primed summaries", "summarize subs", "english previews", "primed listening summaries" | `dojo-prompts/primed-summaries.md` |
| "sync wanikani", "import wanikani words", "mark wanikani words known" | `dojo-prompts/wanikani-sync.md` |
| "sync migaku", "import migaku words", "mark migaku words known" | `dojo-prompts/migaku-sync.md` |
| "download a video", "download this" | Use yt-dlp (see below) |

When a skill is triggered, read the full skill file first, then follow its workflow step by step.

## Dependency checks

Before running any skill, check that required programs are installed. **Only install something if it's missing.** Do not reinstall programs that are already present.

Check with `which` or `command -v` for CLI tools, and `python3 -m pip show` for Python packages:

```bash
# CLI tools
command -v yt-dlp >/dev/null 2>&1 || echo "MISSING: yt-dlp"
command -v ffprobe >/dev/null 2>&1 || echo "MISSING: ffprobe"
command -v ffmpeg >/dev/null 2>&1 || echo "MISSING: ffmpeg"

# Python packages
python3 -m pip show fugashi >/dev/null 2>&1 || echo "MISSING: fugashi"
python3 -m pip show genanki >/dev/null 2>&1 || echo "MISSING: genanki"
python3 -m pip show requests >/dev/null 2>&1 || echo "MISSING: requests"
```

**Special case — subs2cia:** Even if subs2cia is installed, you must verify it's the correct fork **and that it's up to date**. Check with:
```bash
python3 -m pip show subs2cia 2>/dev/null | grep -i "home-page\|location"
```
If the installed version is NOT from `github.com/mattvsjapan/subs2cia`, uninstall it and install the correct fork:
```bash
python3 -m pip uninstall --break-system-packages -y subs2cia
python3 -m pip install --break-system-packages git+https://github.com/mattvsjapan/subs2cia.git
```
If it IS the correct fork, upgrade it to ensure you have the latest features:
```bash
python3 -m pip install --break-system-packages --upgrade git+https://github.com/mattvsjapan/subs2cia.git
```

If a required tool is missing, just install it and move on. No need to ask — but don't reinstall things that are already there.

## Important

- **Processing videos**: Always use yt-dlp and always produce MP4. **Cap at 1080p** (`height<=1080`) — never download 1440p/4K; it only bloats the file and the Anki deck. Pick the tallest tier up to 1080p, using H.264 as a tie-breaker at equal resolution (`-S "res,vcodec:h264"`). Pass `--cookies-from-browser chrome` (the user's YouTube Premium session) so Premium bonus-bitrate formats actually download instead of silently failing and falling back to a tiny legacy 360p file. After yt-dlp writes the file, rename it to a short romanized name: underscores, a few key words rather than the whole title, starting with a capital letter; folder names follow the same rule (see `process-content.md` for detailed naming rules):
  ```bash
  # Single video
  yt-dlp --cookies-from-browser chrome -f "bv*[height<=1080]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]" -S "res,vcodec:h264" --merge-output-format mp4 -o "%(title)s.%(ext)s" "URL"
  # Playlist or channel
  yt-dlp --cookies-from-browser chrome -f "bv*[height<=1080]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]" -S "res,vcodec:h264" --merge-output-format mp4 -o "%(playlist_index)03d_%(title)s.%(ext)s" "URL"
  # Then rename to a short romanized name, capitalized, with underscores
  # e.g. 「機械オンチに「API」を説明する動画」→ Kikai_onchi_api.mp4
  ```
- **subs2cia**: Any step that uses subs2cia must use [mattvsjapan's fork](https://github.com/mattvsjapan/subs2cia). Install with: `python3 -m pip install --break-system-packages git+https://github.com/mattvsjapan/subs2cia.git`
- **Transcription provider**: Any skill that transcribes audio/video (create-srt, find-mistakes, style-guide) uses **ElevenLabs Scribe v2** only — run `dojo-prompts/scripts/transcribe.py --provider elevenlabs`; don't offer Soniox. If `$ELEVENLABS_API_KEY` is not set, ask the user to paste it before transcribing.
- **Transcribe one file at a time, always**: never run multiple transcriptions concurrently — not in parallel subagents and not as backgrounded shell jobs. STT accounts allow only a few concurrent jobs (as low as 2), and over-limit uploads die as mid-upload connection resets that waste usage on retries. This applies to every skill that calls `transcribe.py`.
- **Primed Listening**: `dojo-prompts/primed-listening.lua` is an mpv script, not an AI skill. To install it, copy it to `~/.config/mpv/scripts/`.
