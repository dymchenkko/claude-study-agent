---
name: study-setup
description: "First-run onboarding - check this machine, install what is missing, pick the right semantic-search mode for the hardware, create the first subject. Use on first run, on a new computer, or when the user asks about setup, requirements, installation or search being slow / not working."
metadata: {"matrix": {"emoji": "🛠️", "execution_mode": "bash", "category_name": "education", "requires": {"bins": ["python3"]}}}
---

# Setup / onboarding

Arguments, from the user's message: `[auto|cpu|off]`

1. Run `$STUDY_ROOT/.tools/study doctor` and read the report (machine, tutor backend, tools, current and recommended search mode).
   If it can't run because there is no Python at all (rare): on macOS run `xcode-select --install` (I click
   Install in the dialog; it's also what reads scanned PDFs), on Linux `sudo apt install python3`; then rerun it.
   If the `Python` line says `needs 3.10+`: ask me in one line, e.g. "Your Python is too old for
   meaning-based search (3.9). Install a newer one? ~1 min, no password." On yes, if `brew` exists run
   `brew install python`, else download `https://astral.sh/uv/install.sh` with curl, then run it with `sh` and then
   `~/.local/bin/uv python install 3.13`. Rerun `study doctor`: the line now says `ok` (`study` switches to the
   newer Python by itself) and the recommended mode is no longer `off` because of Python.
2. Tell me in ≤ 120 words, in plain words:
   - which file types I can already import, and which tools are missing (only the ones for file types I said I
     have — ask if unsure);
   - the search mode it recommends and why. The modes:
     - **auto** (Apple Silicon): uses the Apple GPU for indexing. Best when available.
     - **cpu** (any other Mac or Linux, ≥ 4 GB RAM): same results; indexing ~0.1 s per passage
       (a 90-min lecture ≈ 10 s, a 300-page PDF ≈ 1 min, once).
     - **off** (Windows without WSL, < 4 GB RAM or < 1 GB free disk, or "keep it light"):
       Grep only. Everything works; only meaning-based / cross-language search is missing.
3. Ask me one short question: which mode (recommended first; accept the argument if given). Also offer to install
   the missing tools; show the exact commands from the report and run them only after I agree.
4. Run `$STUDY_ROOT/.tools/study setup --mode <mode>` in the background (first time ~1–2 min: llama.cpp ~15 MB +
   a 310 MB model, no Python packages). When done, show the two `OK` lines (device and timing). If it says
   `.tools/.venv` is no longer used, offer to delete it (~1 GB, the old PyTorch setup).
5. If the Whisper model is missing and I have lectures as video/audio, offer the download from the README.
6. If no subject exists, ask for the subject name and exam date, run `$STUDY_ROOT/.tools/study new "<Subject>"`,
   and fill in the date and exam format in its `CLAUDE.md` from what I tell you.
7. End with the next action: drop files into `<Subject>/materials/`, then `ingest <Subject>`, then `today`.
