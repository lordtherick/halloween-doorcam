#!/usr/bin/env bash
# ==============================================================================
# 🎃 Halloween Doorcam - Voice & Sound Tester Launcher
# ==============================================================================
# Intent:
#   Sets up an isolated Python virtual environment (`.venv`) on the host system
#   if not already present, ensures necessary TTS packages (edge-tts, rich,
#   python-dotenv) are installed, and runs `test_voice.py` seamlessly.
#
# Usage:
#   ./test_voice.sh                                # Interactive voice studio
#   ./test_voice.sh --text "I see you, mortal!"    # Quick phrase audition
#   ./test_voice.sh --preset deep_phantom_us       # Test a specific preset
#   ./test_voice.sh --list-voices                  # Browse available voices
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv"

# 1. Bootstrap Python virtual environment if missing and possible
if [ ! -d "${VENV_DIR}" ]; then
    if python3 -m venv "${VENV_DIR}" >/dev/null 2>&1; then
        "${VENV_DIR}/bin/pip" install --upgrade pip >/dev/null 2>&1 || true
        "${VENV_DIR}/bin/pip" install edge-tts python-dotenv rich numpy >/dev/null 2>&1 || true
    fi
fi

# 2. Execute test_voice.py within the virtual environment or fallback to host python3
if [ -x "${VENV_DIR}/bin/python3" ]; then
    exec "${VENV_DIR}/bin/python3" "${SCRIPT_DIR}/test_voice.py" "$@"
else
    exec python3 "${SCRIPT_DIR}/test_voice.py" "$@"
fi
