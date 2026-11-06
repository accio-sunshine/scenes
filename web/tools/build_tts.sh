#!/usr/bin/env bash
# Rebuild web/vendor/scene_tts.js (meSpeak/eSpeak text-to-speech bundle used by the page for "Typed text" speech).
# Needs node + npm. Run from anywhere:  bash web/tools/build_tts.sh
set -euo pipefail
WEB="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
cp "$WEB/tools/scene_tts_entry.js" "$TMP/entry.js"
cd "$TMP" && npm init -y >/dev/null && npm install --silent mespeak@2.0.2 esbuild@0.20.2
npx esbuild entry.js --bundle --format=iife --platform=browser --minify --outfile=bundle.js
{ head -6 "$WEB/vendor/scene_tts.js"; cat bundle.js; } > "$TMP/out.js" && mv "$TMP/out.js" "$WEB/vendor/scene_tts.js"
echo "wrote $WEB/vendor/scene_tts.js"
