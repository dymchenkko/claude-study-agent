# Claude Study Agent

**An AI study tutor for university courses that teaches from *your own* lecture slides, PDFs and recordings — and remembers what you forgot.**

Built on [Claude Code](https://claude.com/claude-code). Drop in your course materials, and it turns them into a searchable knowledge base, teaches you one small idea at a time, quizzes you with spaced repetition, tracks your mistakes, and builds mock exams in your real exam format.

No API keys. It runs on your Claude Pro/Max login, and all data stays in your local folder.

---

## Why this one?

Unlike a general chatbot that answers from memory, this tutor:

- **Grounds every answer in your materials.** It searches your converted slides, PDFs and lecture transcripts and cites them, like `(Lecture3.pdf p.12)` or `(Lecture5.mp4 [00:14:30])`.
- **Searches by meaning, offline (optional).** A small local embedding model finds the right slide even when you use other words or another language than the lecturer. It runs on your Mac or PC, not in the cloud.
- **Transcribes lectures locally.** Video and audio are transcribed on your machine with whisper.cpp, with timestamps, so you can search a 90-minute recording in seconds.
- **Remembers you.** Each topic has a level and a spaced-repetition schedule (1 → 3 → 7 → 16 → 35 days). Every wrong answer is logged with the misconception behind it, and re-tested until it is fixed.
- **Teaches like a tutor, not a chatbot.** Short explanations (≤150 words), one micro-task at a time, hints before answers, and honest grading (✅ / ⚠️ / ❌).
- **Prepares you for the real exam.** Mock exams and quizzes match your course's exam format, and the weak-spot report tells you what to revise.

## Commands

Once set up, open Claude Code in the folder and type:

| Command | What it does |
|---|---|
| `/today` | **Start here.** A 15-minute session: due reviews → next topic with micro-tasks → one exam-style question |
| `/learn <topic>` | Tutor one topic step by step from your own materials |
| `/review` | Spaced-repetition recall of everything that is due, across all subjects |
| `/quiz <subject> weak 10` | Multiple-choice and practice questions. Add `html` for a clickable, self-grading quiz |
| `/exam <subject>` | A full mock exam in your exam format, graded, with a weak-spot report and revision plan |
| `/ingest <subject>` | Convert newly added files (or a lecture video URL) to searchable text and update the topic map |
| `/status` | Dashboard: progress per subject, reviews due, days to each exam |
| `/setup` | First run: checks your machine, installs what is missing, picks the right search mode, creates your first subject |

You can also just talk to it: *"explain the Krebs cycle using lecture 4"*, *"I have 10 minutes"*, *"I have the exam in 5 days"*.

## How it works

```
~/Study/
  CLAUDE.md               ← the tutor's rules (edit freely)
  .claude/skills/         ← the commands above
  .tools/study            ← helper: convert materials, create subjects, search, doctor, setup
  .tools/semantic.py      ← optional local semantic search (EmbeddingGemma 2)
  _template/              ← blank subject skeleton
  <Subject>/
    CLAUDE.md             ← your course facts: exam date, format, lecturer emphasis
    syllabus.md           ← topic map with sources, built from your materials
    progress.md           ← level and next review date per topic (the tutor's memory)
    mistakes.md           ← every wrong answer and the misconception behind it
    materials/            ← your originals (never modified)
    converted/            ← searchable text with page / slide / [timestamp] markers
    exams/                ← generated quizzes and mock exams
    sessions/             ← one short log per study session
```

Your originals are never changed. Everything the tutor learns about you is plain Markdown you can read and edit.

## Requirements

| | Minimum (works everywhere) | With semantic search (optional) |
|---|---|---|
| Claude | [Claude Code](https://claude.com/claude-code) with a Pro or Max plan | same |
| OS | macOS or Linux (Windows: use WSL) | macOS on **Apple Silicon** (M1 or newer), or Linux. Not Intel Macs (no current PyTorch) |
| Python | 3 | **3.10+** |
| RAM | whatever Claude Code needs | **8 GB** minimum, 16 GB recommended |
| Free disk | the size of your materials | **+ ~4 GB** (≈1 GB Python packages, ≈1.5 GB model, a few MB of index per subject) |
| GPU | – | optional: Apple Silicon or NVIDIA makes indexing ~30× faster |
| Network | for installs only | once, to download the model; afterwards fully offline |

Command-line tools, each needed only for its file type:

```bash
brew install poppler ffmpeg yt-dlp whisper-cpp    # PDF (pdftotext), video/audio, lecture links, transcription
pip install markitdown                            # PPTX / DOCX / XLSX → text
```

On Linux use your package manager (`apt install poppler-utils ffmpeg`, `pip install yt-dlp`) and build whisper.cpp. `./.tools/study doctor` lists what is missing.

Whisper model for transcription (about 575 MB, not in the repo). Skip it if you only have slides and PDFs:

```bash
mkdir -p ~/Study/.tools/models
curl -L -o ~/Study/.tools/models/ggml-large-v3-turbo-q5_0.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo-q5_0.bin
```

## Quick start

```bash
# 1. Clone into ~/Study (the skills expect this exact path)
git clone https://github.com/dymchenkko/claude-study-agent.git ~/Study
cd ~/Study

# 2. Open Claude Code and let it onboard you
claude            # accept the "trust this folder" prompt the first time
# then type /setup
```

`/setup` checks your machine, tells you which tools are missing, recommends a search mode (below), installs it, and creates your first subject. Then drop your files into `<Subject>/materials/{slides,pdfs,videos,notes,other}/`, type `/ingest <Subject>`, and fill in `<Subject>/CLAUDE.md` (exam date, format, what the lecturer emphasises). After that, `/today` every day.

Prefer the terminal? The same steps by hand:

```bash
./.tools/study doctor                      # what this machine has, and the recommended mode
./.tools/study setup                       # install semantic search in that mode (or --mode auto|cpu|off)
./.tools/study new "Biology"
./.tools/study ingest "Biology"            # or: --url <video-link> for a recorded lecture
```

## Semantic search: choose your mode

Plain search (Grep) only finds the exact words you type. Semantic search compares *meaning*: a question like "how do I simplify a logic function" finds the Karnaugh-map slides, and a Polish question finds an English lecture. It uses [EmbeddingGemma 2](https://huggingface.co/google/embeddinggemma-2) (Google, Apache 2.0), loaded text-only (270M parameters), on your own machine.

It is optional. Without it everything still works; the tutor just uses Grep.

| Your machine | Mode | Indexing new files | Each search |
|---|---|---|---|
| Mac with Apple Silicon (M1–M4) | `auto` | Apple GPU: a 90-min lecture in seconds | CPU, ~8–10 s |
| Linux with an NVIDIA GPU | `auto` | CUDA GPU, same speed class | CPU, ~8–10 s |
| Linux / other without a GPU, 8 GB+ RAM | `cpu` | ~1 s per passage: a lecture ≈ 1–2 min, a 300-page PDF ≈ 5 min (once) | ~8–10 s |
| Intel Mac, < 8 GB RAM, < 4 GB free disk, or you want it light | `off` | – | Grep only |

Why `auto` searches on the CPU: a search embeds one short sentence, where starting up the GPU costs more than it saves (measured on an M2 Pro: 8 s and 1.3 GB on CPU vs 18 s and 2.6 GB on the GPU). Indexing embeds hundreds of passages, where the GPU is ~30× faster. Results are identical either way.

`study setup` writes your choice to `.tools/config.json`. To force a device for one command: `STUDY_DEVICE=cpu ./.tools/study search ...`.

### When exactly does the local model run?

| Moment | What it does | Where |
|---|---|---|
| `/setup` / `study setup` | downloads the model once (~1.5 GB) and indexes the subjects you already have | GPU (`auto`) |
| `/ingest` / `study ingest` | after converting, embeds **only new or changed** files into `.tools/index/<Subject>/` | GPU (`auto`) |
| `study search` — the tutor calls it when `/learn` looks up a topic, `/quiz` and `/exam` collect sources for questions, `/review` finds the source of a past mistake, and when you ask about a topic in plain chat | loads the model, embeds your **one** question, compares it with the stored index, prints the top passages with `(file p.N)` citations | CPU |

It does **not** run for exact terms, formulas or names (the tutor uses Grep for those), for transcription (that is whisper.cpp), or for the teaching itself (that is Claude). It only ever reads `converted/`, and after the first download it never uses the network.

Optional: `alias study=~/Study/.tools/study` to make the helper a single word.

Try it without your own files first: the repo includes `Example-Subject/` as a demo subject.

## Tips

- Run `/ingest` inside Claude instead of the plain `study ingest`. It also updates the topic map in `syllabus.md`.
- Long lecture transcripts cost more usage. The tutor searches `converted/` and reads only the relevant parts.
- New computer? Clone, copy your subject folders over, and run `/setup`. It rebuilds the search index from `converted/`, so `.tools/index/` never needs copying.
- Your own subjects are excluded by `.gitignore`. Only `_template/` and `Example-Subject/` are tracked, so your course materials and progress stay private if you push your copy.

## Contributing

Ideas, issues and pull requests are welcome. The commands are plain Markdown skills in `.claude/skills/`, so adding one is a good first contribution.

## License

MIT. See [LICENSE](LICENSE).

---

If this helped you study, a ⭐ helps other students find it.
