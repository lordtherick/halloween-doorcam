#!/usr/bin/env python3
"""
🎃 Halloween Doorcam - Spooky Sound Effects & AudioCraft CLI Manager
===================================================================
Command-line utility to preview, generate, and audition atmospheric Halloween
sound effects and stingers for the Halloween Doorcam before or during deployment.

Capabilities:
-------------
- Inspect cache status of all pre-configured sound effects.
- Pre-generate/warm all effects using procedural synthesis or AudioCraft.
- Audition effects directly through connected speakers/Bluetooth.
- Synthesize custom one-off sound effects from arbitrary text prompts.
"""

import os
import sys
import argparse
import subprocess
from pathlib import Path

# Auto-re-execute inside local .venv if not already running in it
# Ensures rich, numpy, and dependencies are cleanly resolved on host
SCRIPT_DIR = Path(__file__).resolve().parent
VENV_PYTHON = SCRIPT_DIR / ".venv" / "bin" / "python3"
if VENV_PYTHON.exists() and sys.executable != str(VENV_PYTHON):
    try:
        if subprocess.run([str(VENV_PYTHON), "-c", "import sys"], capture_output=True).returncode == 0:
            os.execv(str(VENV_PYTHON), [str(VENV_PYTHON)] + sys.argv)
    except Exception:
        pass

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

from spooky_fx import (
    DEFAULT_FX_PROFILES,
    FX_DIR,
    get_fx_path,
    is_fx_cached,
    generate_sound_effect,
    prewarm_sound_effects,
    play_sound_effect,
    AUDIOCRAFT_AVAILABLE
)


def list_sound_effects() -> None:
    """
    Display a formatted overview of all configured sound effects and their cache status.

    Checks the filesystem to determine whether an MP3 or WAV version of each effect
    exists in `audio_cache/fx/`. If the `rich` library is installed, renders a styled
    terminal table with color-coded status badges, effect durations, and descriptive
    prompts; otherwise, prints clean ASCII text.

    Returns:
        None

    Example:
        >>> list_sound_effects()
        # Displays table with 'motion_detected', 'riddle_intro', etc.
    """
    console = Console() if RICH_AVAILABLE else None

    if RICH_AVAILABLE:
        table = Table(
            title="🎃 Halloween Doorcam Sound Effects Library",
            show_header=True,
            header_style="bold orange3"
        )
        table.add_column("#", style="dim", width=4)
        table.add_column("Effect Key", style="bold cyan")
        table.add_column("Title", style="bold white")
        table.add_column("Duration", style="green", justify="center")
        table.add_column("AudioCraft Prompt", style="dim")
        table.add_column("Status", justify="center")

        for idx, (key, profile) in enumerate(DEFAULT_FX_PROFILES.items(), 1):
            cached = is_fx_cached(key)
            status_str = "[bold green]● Cached (Ready)[/bold green]" if cached else "[yellow]○ Not Cached[/yellow]"
            dur_str = f"{profile['duration']}s"
            table.add_row(str(idx), key, profile["title"], dur_str, profile["prompt"], status_str)

        console.print()
        console.print(table)
        console.print()
    else:
        print("\nHalloween Doorcam Sound Effects Library:")
        for idx, (key, profile) in enumerate(DEFAULT_FX_PROFILES.items(), 1):
            status = "Cached" if is_fx_cached(key) else "Not Cached"
            print(f" [{idx}] {key} - {profile['title']} ({status})")
            print(f"     Prompt: {profile['prompt']}")


def main() -> None:
    """
    Main entry point for the Sound Effects & AudioCraft CLI tool.

    Parses command-line arguments to handle listing, bulk pre-warming, single
    audition playback, and custom text-to-audio generation. If invoked without
    arguments, launches an interactive terminal menu prompt.

    Supported CLI Flags:
      --list, -l: Print summary table of effects and cache status.
      --generate-all, -g: Generate and cache all default effects.
      --audiocraft: Direct generation to use Meta's AudioCraft if available.
      --play, -p <key>: Audition a specific sound effect through system audio.
      --prompt <text>: Synthesize a custom effect from a natural language prompt.
      --name <str>: Custom identifier key to use alongside --prompt.
      --force, -f: Invalidate cache and force regeneration.

    Returns:
        None

    Example:
        $ ./generate_fx.py --list
        $ ./generate_fx.py --play motion_detected
        $ ./generate_fx.py --generate-all --audiocraft
    """
    parser = argparse.ArgumentParser(
        description="🎃 Halloween Doorcam: Sound Effects & AudioCraft CLI Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  List all sound effects and cache status:
    ./generate_fx.py --list

  Pre-generate all sound effects:
    ./generate_fx.py --generate-all

  Audition a sound effect (e.g. motion_detected or correct_answer):
    ./generate_fx.py --play motion_detected

  Generate with AudioCraft:
    ./generate_fx.py --generate-all --audiocraft
"""
    )
    parser.add_argument("--list", "-l", action="store_true", help="List all sound effects and their cache status")
    parser.add_argument("--generate-all", "-g", action="store_true", help="Pre-generate and cache all standard sound effects")
    parser.add_argument("--audiocraft", action="store_true", help="Use AudioCraft (AudioGen) if installed instead of procedural audio")
    parser.add_argument("--play", "-p", type=str, help="Play and audition a specific sound effect key")
    parser.add_argument("--prompt", type=str, help="Generate a custom sound effect using a text prompt")
    parser.add_argument("--name", type=str, help="Name/key for custom sound effect (used with --prompt)")
    parser.add_argument("--force", "-f", action="store_true", help="Force regeneration of existing cached sound effects")

    args = parser.parse_args()

    # Default action if no flags passed: show list and interactive prompt
    if not (args.list or args.generate_all or args.play or args.prompt):
        list_sound_effects()
        print("Options:")
        print("  [g] Generate and pre-warm all sound effects now")
        print("  [p] Play/audition a sound effect")
        print("  [q] Quit")
        try:
            choice = input("\nChoose option: ").strip().lower()
            if choice == "g":
                prewarm_sound_effects(use_audiocraft=args.audiocraft, force=True)
                list_sound_effects()
            elif choice == "p":
                fx_name = input("Enter sound effect key to play (e.g. motion_detected, correct_answer): ").strip()
                if fx_name in DEFAULT_FX_PROFILES:
                    print(f"Playing '{fx_name}'...")
                    play_sound_effect(fx_name)
                else:
                    print(f"Unknown effect key '{fx_name}'.")
        except (KeyboardInterrupt, EOFError):
            print()
        return

    # Handle --list flag
    if args.list:
        list_sound_effects()

    # Handle --generate-all flag
    if args.generate_all:
        prewarm_sound_effects(use_audiocraft=args.audiocraft, force=args.force)
        list_sound_effects()

    # Handle custom prompt generation
    if args.prompt:
        name = args.name or "custom_fx"
        print(f"Generating custom sound effect '{name}' with prompt: \"{args.prompt}\"...")
        DEFAULT_FX_PROFILES[name] = {
            "title": name.replace("_", " ").title(),
            "prompt": args.prompt,
            "duration": 3.5,
            "description": "Custom sound effect"
        }
        path = generate_sound_effect(name, force_regenerate=True, use_audiocraft=args.audiocraft)
        if path:
            print(f"✓ Successfully generated custom FX: {path}")
        else:
            print("✗ Failed to generate custom FX.")

    # Handle --play audition flag
    if args.play:
        print(f"Auditioning sound effect: '{args.play}'...")
        success = play_sound_effect(args.play)
        if not success:
            print(f"Could not play '{args.play}'. Make sure an audio output device is connected.")


if __name__ == "__main__":
    main()
