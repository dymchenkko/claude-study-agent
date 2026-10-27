## Running on Anna
These rules come first; they fix what went wrong in testing.
- **Study folder.** `$STUDY_ROOT` is `~/Study` on a local agent and `$ANNA_WORKSPACE_DIR/Study` on a cloud agent.
  If it does not exist, download it (there is no git on cloud agents) and say so in one line:
  `cd "$ANNA_WORKSPACE_DIR" && curl -sL https://github.com/dymchenkko/claude-study-agent/archive/refs/heads/main.tar.gz | tar xz && mv claude-study-agent-main Study`
- **Never fake anything.** Never write a stand-in for `.tools/study` or any other tool, and never create
  materials. If a command fails or the materials are missing, show the error, say what is missing, and stop
  until I decide. Teaching from general knowledge needs my yes first.
- **Edit memory files in place.** Before changing `progress.md` or `mistakes.md`, print it. Change only the
  rows you touched (or append a new row), keep the header, the notes and every other row, and write the whole
  file back. Never write them with `echo … >` or a heredoc that replaces the file. Append to the session log.
  Afterwards print the file again to check that no row was lost.
- **Cite exact file names** as they appear under `converted/`, e.g. `(Lecture1-Membrane-transport.pdf p.2)`.
- **Levels follow the skill.** In `study-learn` the Level comes from the teach-back; if I stop before it, set
  Level 1 (seen) and keep the row's other topics untouched.
