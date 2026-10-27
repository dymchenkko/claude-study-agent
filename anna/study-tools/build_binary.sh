#!/bin/bash
# Build study-tools into a multi-file binary and package it the way the Anna Agent installs it:
#   dist/study-tools-<platform>.tar.gz  =  bin/study-tools + bin/_internal/ + manifest.json
# Usage: ./build_binary.sh [platform]   (platform defaults to this machine, e.g. darwin-arm64)
# Needs PyInstaller (pip install pyinstaller). The release workflow runs this on each platform.
#
# --onedir, not --onefile: a onefile binary unpacks Python to a new temp dir on every start, and macOS
# re-scans those files each time (6-7 s measured), past the Agent's 5 s describe timeout.
set -euo pipefail
cd "$(dirname "$0")"

os=$(uname -s | tr '[:upper:]' '[:lower:]')
arch=$(uname -m)
case "$arch" in amd64|x64) arch=x86_64 ;; arm64) [[ $os == linux ]] && arch=aarch64 ;; esac
platform=${1:-$os-$arch}
version=$(python3 -c "import json; print(json.load(open('executa.json'))['version'])")

rm -rf build dist study-tools.spec
pyinstaller --onedir --name study-tools --clean --noupx --log-level WARN study_tools.py

stage=dist/stage
mkdir -p "$stage/bin"
mv dist/study-tools/study-tools dist/study-tools/_internal "$stage/bin/"
cat > "$stage/manifest.json" <<EOF
{
  "name": "study-tools",
  "version": "$version",
  "runtime": { "binary": { "entrypoint": "bin/study-tools", "permissions": { "bin/study-tools": "0o755" } } }
}
EOF

# The packaged binary must answer describe over stdio, fast, before we ship it. The first start of fresh files
# is slow on macOS (a one-time security scan; the Agent allows 60 s right after install), so time the second.
describe='{"jsonrpc":"2.0","method":"describe","id":1}'
echo "$describe" | "$stage/bin/study-tools" >/dev/null
start=$(python3 -c 'import time; print(time.time())')
echo "$describe" | "$stage/bin/study-tools" | python3 -c \
  "import sys, json, time; m = json.load(sys.stdin)['result']; assert m['version'] == '$version', m['version']; \
s = time.time() - $start; print(f'describe ok: {m[\"name\"]} {m[\"version\"]}, {len(m[\"tools\"])} tools, {s:.2f} s'); \
assert s < 4, 'describe too slow for the 5 s timeout'"

tar -C "$stage" -czf "dist/study-tools-$platform.tar.gz" bin manifest.json
echo "built dist/study-tools-$platform.tar.gz"
