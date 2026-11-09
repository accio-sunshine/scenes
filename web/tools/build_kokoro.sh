#!/usr/bin/env bash
# Rebuild web/vendor/scene_kokoro.js and web/vendor/ort/ (Kokoro text-to-speech for "Typed text", engine Kokoro).
# Needs node + npm (network for the packages). Run from anywhere:  bash web/tools/build_kokoro.sh
# --ignore-scripts: onnxruntime-node's postinstall download is not needed for the browser bundle.
set -euo pipefail
WEB="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
cp "$WEB/tools/kokoro_entry.js" "$TMP/entry.js"
cd "$TMP" && npm init -y >/dev/null && npm install --silent --ignore-scripts kokoro-js@1.2.1 esbuild@0.20.2
npx esbuild entry.js --bundle --format=iife --platform=browser --minify --legal-comments=eof --outfile="$WEB/vendor/scene_kokoro.js"
mkdir -p "$WEB/vendor/ort"; rm -f "$WEB/vendor/ort/"*
cp node_modules/onnxruntime-web/dist/ort-wasm-simd-threaded.jsep.{mjs,wasm} "$WEB/vendor/ort/"
node -e 'const p=require("./node_modules/onnxruntime-web/package.json"); console.log(`onnxruntime-web ${p.version} (wasm, JSEP build), ${p.license} licence, Copyright (c) Microsoft Corporation. https://github.com/microsoft/onnxruntime`)' > "$WEB/vendor/ort/NOTICE"
echo "wrote $WEB/vendor/scene_kokoro.js and $WEB/vendor/ort/ ($(cat "$WEB/vendor/ort/NOTICE" | cut -d" " -f1,2))"
