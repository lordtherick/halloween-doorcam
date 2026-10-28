#!/usr/bin/env bash
# ==============================================================================
# 🎃 Halloween Doorcam - Device Setup Wizard Launcher
# ==============================================================================
# Intent:
#   Convenience launcher to execute `setup_devices.py` on the Linux host.
#   Detects Video4Linux2 webcams, Bluetooth speakers, and PipeWire/ALSA
#   microphones, guiding the user to configure `.env` with validated device nodes.
#
# Usage:
#   ./setup_devices.sh              # Interactive setup wizard
#   ./setup_devices.sh --list       # Quick device enumeration
#   ./setup_devices.sh -h           # View all flags
# ==============================================================================
set -e

# Resolve directory of this script to locate setup_devices.py
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Execute setup_devices.py forwarding all arguments
exec python3 "${SCRIPT_DIR}/setup_devices.py" "$@"
