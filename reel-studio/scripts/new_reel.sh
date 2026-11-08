#!/usr/bin/env bash
# Create a new vertical reel project from the Reel Studio template.
#   new_reel.sh <dir>
# Copies the template (1080x1920, dark/red look, Heebo Hebrew font) and puts GSAP
# in assets/vendor so renders work offline and never wait on a CDN.
set -euo pipefail
dir=${1:?usage: new_reel.sh <dir>}
here=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
[[ -e "$dir/index.html" ]] && { echo "$dir already has index.html — not overwriting"; exit 1; }
mkdir -p "$dir"
cp -r "$here/templates/reel/." "$dir/"
mkdir -p "$dir/assets/vendor" "$dir/assets/audio" "$dir/assets/media"
tmp=$(mktemp -d)
(cd "$tmp" && npm pack -q gsap@3.15.0 >/dev/null && tar xzf gsap-*.tgz)
cp "$tmp/package/dist/gsap.min.js" "$dir/assets/vendor/gsap.min.js"
rm -rf "$tmp"
echo "created $dir"
echo "  index.html            root: backdrop + scenes + captions + voice"
echo "  compositions/*.html   one file per scene"
echo "  assets/               fonts, vendor/gsap.min.js, voice.mp3, words.json, media"
