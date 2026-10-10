# Claude Study Agent

**An AI study tutor for university courses that teaches from *your own* lecture slides, PDFs and recordings — and remembers what you forgot.**

Built on [Claude Code](https://claude.com/claude-code). Drop in your course materials, and it turns them into a searchable knowledge base, teaches you one small idea at a time, quizzes you with spaced repetition, tracks your mistakes, and builds mock exams in your real exam format.

No API keys. It runs on your Claude Pro/Max login, and all data stays in your local folder.

---

## Why this one?

Unlike a general chatbot that answers from memory, this tutor:

- **Grounds every answer in your materials.** It searches your converted slides, PDFs and lecture transcripts and cites them, like `(Lecture3.pdf p.12)` or `(Lecture5.mp4 [00:14:30])`.
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

You can also just talk to it: *"explain the Krebs cycle using lecture 4"*, *"I have 10 minutes"*, *"I have the exam in 5 days"*.

## How it works

```
~/Study/
  CLAUDE.md               ← the tutor's rules (edit freely)
  .claude/skills/         ← the seven commands above
  .tools/study            ← helper: convert materials, create subjects
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

- macOS (developed on Apple Silicon). Linux should work with the equivalent packages, but it is untested.
- [Claude Code](https://claude.com/claude-code) with a Claude Pro or Max plan
- Python 3
- Command-line tools:

```bash
brew install poppler ffmpeg yt-dlp whisper-cpp    # pdftotext, ffmpeg, yt-dlp, whisper-cli
pip install markitdown                            # PPTX / DOCX / XLSX → text
```

- Whisper model (about 575 MB, not included in the repo):

```bash
mkdir -p ~/Study/.tools/models
curl -L -o ~/Study/.tools/models/ggml-large-v3-turbo-q5_0.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo-q5_0.bin
```

Transcription is optional. If you only use slides and PDFs, you can skip whisper and `ffmpeg`.

## Quick start

```bash
# 1. Clone into ~/Study (the skills expect this exact path)
git clone https://github.com/dymchenkko/claude-study-agent.git ~/Study
cd ~/Study

# 2. Create a subject
./.tools/study new "Biology"

# 3. Drop your files into Biology/materials/{slides,pdfs,videos,notes,other}/
#    and convert them
./.tools/study ingest "Biology"
#    or a lecture video straight from a link:
./.tools/study ingest "Biology" --url <video-link>

# 4. Fill in Biology/CLAUDE.md (exam date, format, what the lecturer emphasises)

# 5. Start studying
claude            # accept the "trust this folder" prompt the first time
# then type /today
```

Optional: `alias study=~/Study/.tools/study` to make the helper a single word.

Try it without your own files first: the repo includes `Example-Subject/` as a demo subject.

## Tips

- Run `/ingest` inside Claude instead of the plain `study ingest`. It also updates the topic map in `syllabus.md`.
- Long lecture transcripts cost more usage. The tutor searches `converted/` and reads only the relevant parts.
- Your own subjects are excluded by `.gitignore`. Only `_template/` and `Example-Subject/` are tracked, so your course materials and progress stay private if you push your copy.

## Contributing

Ideas, issues and pull requests are welcome. The commands are plain Markdown skills in `.claude/skills/`, so adding one is a good first contribution.

## License

MIT. See [LICENSE](LICENSE).

---

If this helped you study, a ⭐ helps other students find it.
