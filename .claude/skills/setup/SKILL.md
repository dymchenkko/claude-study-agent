---
name: setup
description: First-run onboarding - check this machine, install what is missing, pick the right semantic-search mode for the hardware, create the first subject. Use on first run, on a new computer, or when the user asks about setup, requirements, installation or search being slow / not working.
argument-hint: "[auto|cpu|off]"
---

# Setup / onboarding

1. Run `~/Study/.tools/study doctor` and read the report (machine, tools, current and recommended search mode).
2. Tell me in ≤ 120 words, in plain words:
   - which file types I can already import, and which tools are missing (only the ones for file types I said I
     have — ask if unsure);
   - the search mode it recommends and why. The modes:
     - **auto** (Apple Silicon or NVIDIA GPU): indexes on the GPU, searches on the CPU. Best when available.
     - **cpu** (no supported GPU, ≥ 8 GB RAM): same results, but indexing takes ~1 s per passage
       (a 90-min lecture ≈ 1–2 min, a 300-page PDF ≈ 5 min, once).
     - **off** (Intel Mac, Windows without WSL, < 8 GB RAM or < 4 GB free disk, or "keep it light"):
       Grep only. Everything works; only meaning-based / cross-language search is missing.
3. Ask me one short question: which mode (recommended first; accept the argument if given). Also offer to install
   the missing tools; show the exact commands from the report and run them only after I agree.
4. Run `~/Study/.tools/study setup --mode <mode>` in the background (first time ~3–6 min: ~1 GB of Python
   packages + a ~1.5 GB model download). When done, show the two `OK` lines (device and timing).
5. If the Whisper model is missing and I have lectures as video/audio, offer the download from the README.
6. If no subject exists, ask for the subject name and exam date, run `~/Study/.tools/study new "<Subject>"`,
   and fill in the date and exam format in its `CLAUDE.md` from what I tell you.
7. End with the next action: drop files into `<Subject>/materials/`, then `/ingest <Subject>`, then `/today`.
