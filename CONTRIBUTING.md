# Contributing

Thanks for helping students study better! Issues, ideas and pull requests are all welcome.

## Good first contributions

- **A new command.** Commands are plain Markdown skills in `.claude/skills/<name>/SKILL.md`. Copy an existing one, change the steps, and describe what it does in the front matter.
- **A new file type.** Conversion lives in `.tools/study` (`cmd_ingest`). Keep the location markers (`--- page N ---`, `<!-- Slide number: N -->`, `[hh:mm:ss]`) so citations and search keep working.
- **Linux and Windows (WSL) testing.** Most development happens on macOS; reports and fixes for other platforms are very welcome.
- **Better demo content** in `Example-Subject/` (your own writing only, no copyrighted course material).

## Before you open a pull request

1. Try your change on a real subject: `./.tools/study ingest <Subject>`, then `/learn` or `/quiz` in Claude Code.
2. Never commit personal course materials, progress or mistakes. `.gitignore` excludes your subjects; keep it that way.
3. Keep the tutor rules short: `CLAUDE.md` is read at the start of every session.
4. Describe what you changed and how you tested it.

## Reporting a bug

Open an issue with your OS, the output of `./.tools/study doctor`, the command you ran and what happened. Please remove anything private from logs.

## Code of conduct

By taking part you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).
