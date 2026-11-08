#!/usr/bin/env bash
# Installs the "toolbox" from the reel: ffmpeg, Playwright + Chromium, HyperFrames, Whisper (Hebrew), and checks ElevenLabs.
# Safe to re-run. Usage: setup.sh [--no-whisper]
set -uo pipefail
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
step() { printf '\n\033[1m%s\033[0m\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

step "ffmpeg"
if have ffmpeg; then ok "ffmpeg $(ffmpeg -version | head -1 | awk '{print $3}')"
else
  if   have brew;    then brew install ffmpeg
  elif have apt-get; then (sudo -n true 2>/dev/null && sudo apt-get install -y ffmpeg) || apt-get install -y ffmpeg
  elif have winget;  then winget install -e --id Gyan.FFmpeg
  fi
  have ffmpeg && ok "ffmpeg installed" || warn "install ffmpeg manually: https://ffmpeg.org/download.html"
fi

step "Node.js (HyperFrames needs >= 22)"
if have node; then
  major=$(node -p 'process.versions.node.split(".")[0]')
  [[ $major -ge 22 ]] && ok "node $(node -v)" || warn "node $(node -v) is too old: install Node 22+ (https://nodejs.org)"
else warn "install Node 22+ from https://nodejs.org"; fi

PY=$(command -v python3 || command -v python || true)
step "Python packages (imageio-ffmpeg, Playwright)"
if [[ -n "$PY" ]]; then
  "$PY" -m pip install -q --upgrade imageio-ffmpeg playwright 2>&1 | grep -v -i "warning" || true
  ok "pip packages"
else warn "python3 not found"; fi

step "Playwright Chromium"
if [[ -d /opt/pw-browsers/chromium ]] || ls ~/.cache/ms-playwright/chromium-* >/dev/null 2>&1 || ls "$HOME/Library/Caches/ms-playwright/chromium-"* >/dev/null 2>&1; then
  ok "Chromium already downloaded"
else
  npx -y playwright install chromium && ok "Chromium downloaded" || warn "run: npx playwright install chromium"
fi

step "HyperFrames"
if npx -y hyperframes@latest --version >/dev/null 2>&1; then
  ok "hyperframes $(npx -y hyperframes --version 2>/dev/null | tail -1)"
  npx -y hyperframes doctor 2>&1 | sed 's/^/    /' | tail -12
  warn "optional (you run it): npx hyperframes skills update   # installs HyperFrames' own Claude skills"
else warn "hyperframes failed: check Node 22+ and network"; fi

if [[ "${1:-}" != "--no-whisper" && -n "$PY" ]]; then
  step "Whisper for Hebrew (faster-whisper + ivrit-ai/whisper-large-v3-turbo-ct2)"
  "$PY" -m pip install -q --upgrade faster-whisper 2>&1 | grep -v -i "warning" || true
  if "$PY" -c "import faster_whisper" 2>/dev/null; then
    ok "faster-whisper installed (model ~1.6 GB downloads on first transcription)"
  else warn "pip install faster-whisper failed"; fi
fi

step "ElevenLabs"
if [[ -n "${ELEVENLABS_API_KEY:-}" ]]; then
  ok "ELEVENLABS_API_KEY is set"
  [[ -n "${ELEVENLABS_VOICE_ID:-}" ]] && ok "ELEVENLABS_VOICE_ID=$ELEVENLABS_VOICE_ID" \
    || warn "no ELEVENLABS_VOICE_ID yet: clone your voice with /reel-voice"
else
  warn "set ELEVENLABS_API_KEY (elevenlabs.io → Profile → API keys) to use your cloned voice"
fi

printf '\n\033[1mDone.\033[0m Next: /reel <topic>\n'
