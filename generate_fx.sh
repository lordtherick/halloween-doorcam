#!/usr/bin/env bash
# ==============================================================================
# 🎃 Halloween Doorcam - Sound Effects & AudioCraft CLI Launcher
# ==============================================================================
# Intent:
#   Convenience wrapper script to execute `generate_fx.py` using the host's
#   Python 3 environment. Forwards all CLI flags directly to the Python script.
#
# Usage:
#   ./generate_fx.sh --list
#   ./generate_fx.sh --generate-all
#   ./generate_fx.sh --play motion_detected
#   ./generate_fx.sh --audiocraft
# ==============================================================================
set -e

# Resolve directory of this script to safely locate python scripts
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Execute generate_fx.py forwarding all arguments
exec python3 "${SCRIPT_DIR}/generate_fx.py" "$@"
