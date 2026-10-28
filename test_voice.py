#!/usr/bin/env python3
"""
🎃 Halloween Doorcam - Voice & Sound Tester
Preview, tune, and audition Edge-TTS voices and spooky audio effects
for the Halloween Doorcam before deploying.
"""

import os
import sys
import shutil
import argparse
import asyncio
import subprocess
import tempfile
import re
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Auto-re-execute inside local .venv if not already running in it
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
    from rich.prompt import Prompt, Confirm
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

try:
    import edge_tts
    EDGE_TTS_AVAILABLE = True
except ImportError:
    EDGE_TTS_AVAILABLE = False


ENV_PATH = SCRIPT_DIR / ".env"
AUDIO_CACHE_DIR = SCRIPT_DIR / "audio_cache"
AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Curated Halloween Voice Presets
SPOOKY_PRESETS = [
    {
        "id": "gargoyle_uk",
        "title": "Spooky Gargoyle (British, default)",
        "voice": "en-GB-RyanNeural",
        "rate": "-10%",
        "pitch": "-15Hz",
        "sample": "I am the watcher of the gate. Answer my riddle, foolish mortal, or begone!"
    },
    {
        "id": "deep_phantom_us",
        "title": "Deep Phantom (US Male, commanding)",
        "voice": "en-US-ChristopherNeural",
        "rate": "-15%",
        "pitch": "-22Hz",
        "sample": "Who dares disturb the ancient slumber of the crypt? Speak your name!"
    },
    {
        "id": "crypt_keeper_us",
        "title": "Crypt Keeper (US Male, gruff & dark)",
        "voice": "en-US-GuyNeural",
        "rate": "-12%",
        "pitch": "-18Hz",
        "sample": "Welcome to my haunted doorstep! Trick or treat... smell my feet!"
    },
    {
        "id": "raspy_shadow_us",
        "title": "Raspy Shadow (US Male, eerie whisper tone)",
        "voice": "en-US-EricNeural",
        "rate": "-8%",
        "pitch": "-12Hz",
        "sample": "The shadows are watching you... One wrong answer, and no candy for you!"
    },
    {
        "id": "gothic_witch_uk",
        "title": "Gothic Witch (UK Female, sinister)",
        "voice": "en-GB-SoniaNeural",
        "rate": "-5%",
        "pitch": "-10Hz",
        "sample": "Double, double toil and trouble, fire burn and cauldron bubble! What do you seek, little one?"
    },
    {
        "id": "dark_sorceress_us",
        "title": "Dark Sorceress (US Female, mysterious)",
        "voice": "en-US-JennyNeural",
        "rate": "-8%",
        "pitch": "-14Hz",
        "sample": "Enter if you dare... Solve my Halloween puzzle to earn the sweet treasure."
    },
    {
        "id": "banshee_ie",
        "title": "Ancient Banshee (Irish Male, mythical)",
        "voice": "en-IE-ConnorNeural",
        "rate": "-10%",
        "pitch": "-15Hz",
        "sample": "From the mist of the moors I awaken! Riddle me this before midnight strikes!"
    },
    {
        "id": "vampire_lord_uk",
        "title": "Vampire Lord (UK Male, slow & regal)",
        "voice": "en-GB-ThomasNeural",
        "rate": "-15%",
        "pitch": "-18Hz",
        "sample": "Good evening... Children of the night, what sweet music you make!"
    }
]

# Standard doorcam test dialogues
TEST_DIALOGUES = [
    ("Sample Riddle", "I have no flesh, no feathers, no scales, and no bone. Yet I have fingers and thumbs of my own. What am I?"),
    ("Correct Answer", "You are clever, mortal. You may take a sweet from the bowl."),
    ("Wrong Answer (Costume Reward)", "Wrong! The answer was a glove. But because you wear such a scary costume, you may take a sweet from the bowl anyway!"),
    ("Silent Answer (Costume Reward)", "You are silent! The answer was a glove. But because you wear such a scary costume, you may take a sweet from the bowl!"),
    ("Trick or Treat", "Trick or treat! Smell my feet! Give me something good to eat!"),
    ("Short Spooky Laugh", "Ha ha ha ha ha! Happy Halloween, mortal!")
]


class UI:
    """
    Console user interface helper for the Voice & Sound Tester.

    Renders styled banner panels, section headers, warning badges, and error
    indicators using Rich when installed, or standardized plain text formatting.
    """

    def __init__(self):
        """Initialize the UI console manager."""
        self.console = Console() if RICH_AVAILABLE else None

    def print_banner(self) -> None:
        """Render the Voice & Sound Tester title banner."""
        title = "🎃 Halloween Doorcam - Voice & Sound Tester 🎃"
        subtitle = "Audition Edge-TTS voices, adjust pitch/rate & test your speaker output"
        if self.console:
            self.console.print()
            self.console.print(
                Panel.fit(
                    f"[bold bright_yellow]{title}[/bold bright_yellow]\n[dim]{subtitle}[/dim]",
                    border_style="orange3",
                    padding=(1, 3)
                )
            )
            self.console.print()
        else:
            print("=" * 66)
            print(f" {title} ")
            print(f" {subtitle} ")
            print("=" * 66)
            print()

    def print_section(self, title: str) -> None:
        """
        Display a prominent section header.

        Args:
            title (str): Header text to display.
        """
        if self.console:
            self.console.print(f"\n[bold bright_cyan]─── {title} ───[/bold bright_cyan]")
        else:
            print(f"\n--- {title} ---")

    def print_success(self, msg: str) -> None:
        """
        Display a positive confirmation message with a green checkmark.

        Args:
            msg (str): Success message.
        """
        if self.console:
            self.console.print(f"[bold green]✓[/bold green] {msg}")
        else:
            print(f"[SUCCESS] {msg}")

    def print_warning(self, msg: str) -> None:
        """
        Display a cautionary warning message with a yellow badge.

        Args:
            msg (str): Warning description.
        """
        if self.console:
            self.console.print(f"[bold yellow]![/bold yellow] {msg}")
        else:
            print(f"[WARNING] {msg}")

    def print_error(self, msg: str) -> None:
        """
        Display an error message with a red cross badge.

        Args:
            msg (str): Error description.
        """
        if self.console:
            self.console.print(f"[bold red]✗[/bold red] {msg}")
        else:
            print(f"[ERROR] {msg}")

    def print_info(self, msg: str) -> None:
        """
        Display an informational notice or progress hint.

        Args:
            msg (str): Notice content.
        """
        if self.console:
            self.console.print(f"[dim blue]ℹ[/dim blue] {msg}")
        else:
            print(f"[INFO] {msg}")


ui = UI()


def read_env(path: Path) -> Dict[str, str]:
    """
    Parse environment key-value pairs from the `.env` file into a dictionary.

    Reads lines, strips comments and quotation marks, and returns a key-value mapping.

    Args:
        path (Path): Path to the target `.env` file.

    Returns:
        Dict[str, str]: Dictionary of key-value configurations.

    Example:
        >>> config = read_env(Path(".env"))
        >>> print(config.get("TTS_VOICE"))
        en-GB-RyanNeural
    """
    values = {}
    if not path.exists():
        return values
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    values[key.strip()] = val.strip().strip("'\"")
    except Exception as e:
        ui.print_warning(f"Could not read {path}: {e}")
    return values


def update_env(path: Path, updates: Dict[str, str]) -> bool:
    """
    Update designated keys in the `.env` file while preserving layout and comments.

    Replaces matching lines in-place. If any keys do not exist in the file,
    appends them to the end of the file.

    Args:
        path (Path): Path to `.env` file.
        updates (Dict[str, str]): Dictionary of key-value changes to apply.

    Returns:
        bool: True if file write succeeded; False otherwise.

    Example:
        >>> update_env(Path(".env"), {"TTS_PITCH": "-20Hz"})
        True
    """
    if not path.exists():
        ui.print_error(f".env file not found at {path}")
        return False

    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    new_lines = []
    remaining = set(updates.keys())

    for line in lines:
        stripped = line.strip()
        matched = None
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k = stripped.split("=", 1)[0].strip()
            if k in updates:
                matched = k

        if matched:
            new_lines.append(f"{matched}={updates[matched]}\n")
            remaining.remove(matched)
        else:
            new_lines.append(line)

    for k in remaining:
        new_lines.append(f"{k}={updates[k]}\n")

    try:
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        return True
    except Exception as e:
        ui.print_error(f"Failed to write to {path}: {e}")
        return False


def find_audio_player() -> Optional[List[str]]:
    """
    Discover an available audio player command on the host system.

    Probes the system PATH in prioritized order:
      1. `ffplay` - High quality, silent, zero-window MP3 playback (`-nodisp -autoexit`).
      2. `mpg123` - Lightweight command-line MP3 player (`-q`).
      3. `pw-play` - Native PipeWire audio client.
      4. `paplay` - PulseAudio sample player.
      5. `aplay` - ALSA raw player.

    Returns:
        Optional[List[str]]: Subprocess-executable command prefix, or None if no player found.

    Example:
        >>> player = find_audio_player()
        >>> print(player)
        ['ffplay', '-nodisp', '-autoexit', '-loglevel', 'quiet']
    """
    # Priority 1: ffplay (silent, fast, reliable with mp3)
    if shutil.which("ffplay"):
        return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"]
    # Priority 2: mpg123
    if shutil.which("mpg123"):
        return ["mpg123", "-q"]
    # Priority 3: pw-play (requires ffmpeg or gstreamer backend for mp3)
    if shutil.which("pw-play"):
        return ["pw-play"]
    # Priority 4: paplay
    if shutil.which("paplay"):
        return ["paplay"]
    # Priority 5: aplay
    if shutil.which("aplay"):
        return ["aplay", "-q"]
    return None


def get_cached_audio_path(text: str, voice: str, rate: str, pitch: str) -> Path:
    """
    Compute a deterministic filesystem path for caching synthesized speech audio.

    Hashes the voice, rate, pitch, and text payload with SHA-256 to ensure any
    change to pitch or voice invalidates older cached audio.

    Args:
        text (str): Spoken phrase.
        voice (str): Edge-TTS voice identifier.
        rate (str): Speaking speed offset (e.g. '-10%').
        pitch (str): Voice pitch offset (e.g. '-15Hz').

    Returns:
        Path: Pathlib object pointing to the cached `.mp3` file.

    Example:
        >>> path = get_cached_audio_path("Hello!", "en-GB-RyanNeural", "-10%", "-15Hz")
    """
    payload = f"{voice}|{rate}|{pitch}|{text.strip()}".encode("utf-8")
    content_hash = hashlib.sha256(payload).hexdigest()[:12]
    slug = re.sub(r'[^a-zA-Z0-9]+', '_', text[:20]).strip('_').lower() or "voice"
    return AUDIO_CACHE_DIR / f"{slug}_{content_hash}.mp3"


def clear_audio_cache() -> int:
    """
    Delete all cached `.mp3` files from the `audio_cache/` directory.

    Frees disk space and ensures all subsequent dialogue playback is freshly
    rendered from Microsoft Edge-TTS.

    Returns:
        int: Total number of cache files removed.

    Example:
        >>> count = clear_audio_cache()
        >>> print(f"Removed {count} files.")
    """
    if not AUDIO_CACHE_DIR.exists():
        ui.print_info("Audio cache directory does not exist.")
        return 0

    deleted_count = 0
    total_bytes = 0
    for f in AUDIO_CACHE_DIR.glob("*.mp3"):
        try:
            total_bytes += f.stat().st_size
            f.unlink()
            deleted_count += 1
        except Exception as e:
            ui.print_warning(f"Could not remove {f.name}: {e}")

    size_kb = total_bytes / 1024.0
    ui.print_success(f"Audio cache cleared: removed {deleted_count} file(s) ({size_kb:.1f} KB freed).")
    return deleted_count


async def generate_speech_async(text: str, voice: str, rate: str, pitch: str, output_path: str) -> None:
    """
    Asynchronously synthesize speech using the Python `edge_tts.Communicate` API.

    Args:
        text (str): Text phrase to synthesize.
        voice (str): Voice ShortName (e.g. 'en-GB-RyanNeural').
        rate (str): Speed modification string (e.g. '-10%').
        pitch (str): Pitch modification string (e.g. '-15Hz').
        output_path (str): Destination MP3 filepath.

    Returns:
        None
    """
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await communicate.save(output_path)


def synthesize_and_play(
    text: str,
    voice: str,
    rate: str,
    pitch: str,
    player_cmd: Optional[List[str]] = None,
    use_cache: bool = True
) -> bool:
    """
    Synthesize speech audio via Edge-TTS and play it through the system audio device.

    Checks disk cache for existing audio matching the text and acoustic parameters.
    On cache miss, calls `edge_tts.Communicate` asynchronously to write a temporary
    file, renames it to the cache target, and invokes the chosen CLI audio player.

    Args:
        text (str): Text sentence to speak.
        voice (str): Edge-TTS voice identifier.
        rate (str): Speech rate string.
        pitch (str): Pitch modification string.
        player_cmd (Optional[List[str]]): Specific audio player CLI command list.
        use_cache (bool): If True, checks for and stores audio in disk cache. Defaults to True.

    Returns:
        bool: True if speech was synthesized and played successfully; False on error.

    Example:
        >>> synthesize_and_play("Trick or treat!", "en-GB-RyanNeural", "-10%", "-15Hz")
        True
    """
    if not player_cmd:
        player_cmd = find_audio_player()

    if not player_cmd:
        ui.print_error("No audio player found on system (ffplay, mpg123, or pw-play).")
        return False

    AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = get_cached_audio_path(text, voice, rate, pitch)

    try:
        if use_cache and cache_path.exists() and cache_path.stat().st_size > 0:
            ui.print_info(f"[bold green]Cache Hit[/bold green] Using cached audio: {cache_path.name}")
        else:
            ui.print_info(f"Generating audio with [bold]{voice}[/bold] (rate={rate}, pitch={pitch})...")
            tmp_path = cache_path.with_suffix(".tmp.mp3")
            asyncio.run(generate_speech_async(text, voice, rate, pitch, str(tmp_path)))
            tmp_path.replace(cache_path)

        ui.print_info(f"Playing audio through [bold]{player_cmd[0]}[/bold]...")
        cmd = player_cmd + [str(cache_path)]
        subprocess.run(cmd, check=True)
        return True
    except Exception as e:
        ui.print_error(f"Speech synthesis or playback failed: {e}")
        return False


def list_voices(language_prefix: str = "en") -> None:
    """
    Query Microsoft Edge-TTS for all available cloud neural voices filtered by locale.

    Renders a formatted table displaying voice identifiers, gender, locale,
    and suggested pitch/rate parameters tailored for spooky Halloween dialogue.

    Args:
        language_prefix (str): Two-letter language prefix filter (e.g. 'en', 'es', 'de'). Defaults to 'en'.

    Returns:
        None

    Example:
        >>> list_voices("en")
    """
    ui.print_section(f"Available Edge-TTS Voices ({language_prefix.upper()})")
    try:
        voices = asyncio.run(edge_tts.list_voices())
        matching = [v for v in voices if v["Locale"].lower().startswith(language_prefix.lower())]

        if RICH_AVAILABLE:
            table = Table(title=f"Edge-TTS Voices ({language_prefix.upper()})", show_header=True, header_style="bold magenta")
            table.add_column("Voice Name", style="cyan")
            table.add_column("Gender", style="dim")
            table.add_column("Locale", style="green")
            table.add_column("Suggested Spooky Pitch/Rate", style="yellow")

            for v in matching:
                rec = "-15Hz / -10%" if v["Gender"] == "Male" else "-10Hz / -8%"
                table.add_row(v["ShortName"], v["Gender"], v["Locale"], rec)
            ui.console.print(table)
        else:
            for v in matching:
                print(f" - {v['ShortName']} ({v['Gender']}, {v['Locale']})")
    except Exception as e:
        ui.print_error(f"Failed to fetch voice list: {e}")


def interactive_menu(current_env: Dict[str, str]) -> None:
    """
    Launch the interactive terminal studio for testing, auditioning, and tuning voices.

    Displays an active status dashboard and provides an interactive menu allowing the user to:
      1. Test standard Halloween Doorcam dialogue phrases (riddles, correct/wrong answers).
      2. Synthesize and speak custom arbitrary text.
      3. Audition curated spooky voice presets (Gargoyle, Deep Phantom, Crypt Keeper, Witch, etc.)
         and adopt them into the current active session.
      4. Fine-tune pitch (-25Hz to 0Hz) and speaking speed (-20% to +10%).
      5. Browse the complete online Microsoft Edge-TTS multilingual voice catalog.
      6. Write the tuned configuration directly into the `.env` file.
      7. Purge the cached audio files from `audio_cache/`.

    Args:
        current_env (Dict[str, str]): Current key-value pairs loaded from `.env`.

    Returns:
        None

    Example:
        >>> interactive_menu({"TTS_VOICE": "en-GB-RyanNeural", "TTS_PITCH": "-15Hz"})
    """
    ui.print_banner()

    voice = current_env.get("TTS_VOICE", "en-GB-RyanNeural")
    rate = current_env.get("TTS_RATE", "-10%")
    pitch = current_env.get("TTS_PITCH", "-15Hz")
    output_dev = current_env.get("AUDIO_OUTPUT_DEVICE", "System Default / Bluetooth")

    player = find_audio_player()
    if not player:
        ui.print_error("Could not find ffplay, mpg123, or pw-play. Please install ffmpeg or mpg123.")
        return

    while True:
        if RICH_AVAILABLE:
            ui.console.print(
                Panel(
                    f"[bold white]Current Voice:[/bold white] [bold cyan]{voice}[/bold cyan]  │  "
                    f"[bold white]Rate:[/bold white] [green]{rate}[/green]  │  "
                    f"[bold white]Pitch:[/bold white] [yellow]{pitch}[/yellow]\n"
                    f"[dim]Output Device: {output_dev}  │  Audio Player: {player[0]}[/dim]",
                    title="[bold orange3]Active Voice Settings[/bold orange3]",
                    border_style="orange3"
                )
            )
        else:
            print("\n" + "=" * 50)
            print(f"Current Voice: {voice} | Rate: {rate} | Pitch: {pitch}")
            print(f"Output Device: {output_dev}")
            print("=" * 50)

        print("\nWhat would you like to test?")
        print("  [1] Test Halloween Doorcam dialogues with current voice")
        print("  [2] Speak custom text")
        print("  [3] Audition spooky voice presets (Gargoyle, Phantom, Witch, etc.)")
        print("  [4] Tune pitch and rate (test different deep pitch variations)")
        print("  [5] Select from full Edge-TTS voice list")
        print("  [6] Save current settings to .env")
        print("  [7] Clear audio cache (audio_cache/)")
        print("  [q] Quit")

        try:
            choice = input("\nEnter choice [1-7, q] (default: 1): ").strip().lower()
            if not choice:
                choice = "1"

            if choice in ("q", "quit", "exit"):
                ui.print_info("Exiting voice tester.")
                break

            elif choice == "1":
                # Dialogue submenu
                print("\nSelect dialogue to play:")
                for idx, (title, sample_text) in enumerate(TEST_DIALOGUES, 1):
                    print(f"  [{idx}] {title}: \"{sample_text}\"")
                print("  [a] Play all in sequence")
                print("  [b] Back")
                d_choice = input(f"Choose [1-{len(TEST_DIALOGUES)}, a, b] (default: 1): ").strip().lower()
                if not d_choice:
                    d_choice = "1"

                if d_choice == "b":
                    continue
                elif d_choice == "a":
                    for title, sample_text in TEST_DIALOGUES:
                        ui.print_section(f"Playing: {title}")
                        synthesize_and_play(sample_text, voice, rate, pitch, player)
                elif d_choice.isdigit() and 1 <= int(d_choice) <= len(TEST_DIALOGUES):
                    idx = int(d_choice) - 1
                    title, sample_text = TEST_DIALOGUES[idx]
                    ui.print_section(f"Playing: {title}")
                    synthesize_and_play(sample_text, voice, rate, pitch, player)

            elif choice == "2":
                custom_text = input("\nEnter the phrase for the gargoyle to speak: ").strip()
                if custom_text:
                    synthesize_and_play(custom_text, voice, rate, pitch, player)

            elif choice == "3":
                # Audition presets
                ui.print_section("Spooky Voice Presets")
                if RICH_AVAILABLE:
                    table = Table(title="Spooky Voice Presets", show_header=True, header_style="bold blue")
                    table.add_column("#", style="dim", width=4)
                    table.add_column("Preset Name", style="bold white")
                    table.add_column("Voice ID", style="cyan")
                    table.add_column("Rate / Pitch", style="yellow")
                    table.add_column("Sample Phrase", style="dim")

                    for idx, p in enumerate(SPOOKY_PRESETS, 1):
                        is_active = (p["voice"] == voice and p["rate"] == rate and p["pitch"] == pitch)
                        tag = " [bold green](ACTIVE)[/bold green]" if is_active else ""
                        table.add_row(str(idx), p["title"] + tag, p["voice"], f"{p['rate']} / {p['pitch']}", p["sample"][:40] + "...")
                    ui.console.print(table)
                else:
                    for idx, p in enumerate(SPOOKY_PRESETS, 1):
                        print(f"  [{idx}] {p['title']} ({p['voice']}, rate={p['rate']}, pitch={p['pitch']})")

                print("\nEnter number to audition and adopt preset, [a] to audition all, or [b] to go back:")
                p_choice = input("Choice: ").strip().lower()
                if p_choice == "b" or not p_choice:
                    continue
                elif p_choice == "a":
                    for p in SPOOKY_PRESETS:
                        ui.print_section(f"Auditioning: {p['title']}")
                        synthesize_and_play(p["sample"], p["voice"], p["rate"], p["pitch"], player)
                elif p_choice.isdigit() and 1 <= int(p_choice) <= len(SPOOKY_PRESETS):
                    selected = SPOOKY_PRESETS[int(p_choice) - 1]
                    ui.print_section(f"Auditioning: {selected['title']}")
                    synthesize_and_play(selected["sample"], selected["voice"], selected["rate"], selected["pitch"], player)

                    adopt = input(f"\nAdopt this preset as current setting? [Y/n]: ").strip().lower()
                    if adopt not in ("n", "no"):
                        voice = selected["voice"]
                        rate = selected["rate"]
                        pitch = selected["pitch"]
                        ui.print_success(f"Adopted {selected['title']}.")

            elif choice == "4":
                # Tuning pitch and rate
                ui.print_section("Tune Pitch and Speaking Speed")
                print(f"Current: Voice={voice}, Rate={rate}, Pitch={pitch}\n")
                print("Quick Pitch presets:")
                print("  [1] Deep Demon (-25Hz)")
                print("  [2] Dark Spooky (-20Hz)")
                print("  [3] Gargoyle (-15Hz - default)")
                print("  [4] Slight Depth (-10Hz)")
                print("  [5] Normal (0Hz)")
                print("  [c] Custom value")
                pitch_sel = input("Select pitch (press Enter to keep current): ").strip().lower()
                pitch_map = {"1": "-25Hz", "2": "-20Hz", "3": "-15Hz", "4": "-10Hz", "5": "+0Hz"}
                if pitch_sel in pitch_map:
                    pitch = pitch_map[pitch_sel]
                elif pitch_sel == "c":
                    val = input("Enter pitch (e.g. -18Hz or -50Hz): ").strip()
                    if val:
                        pitch = val if ("Hz" in val or "%" in val) else f"{val}Hz"

                print("\nQuick Speed presets:")
                print("  [1] Very Slow & Dramatic (-20%)")
                print("  [2] Slow (-10% - default)")
                print("  [3] Normal (0%)")
                print("  [4] Fast (+10%)")
                print("  [c] Custom value")
                rate_sel = input("Select rate (press Enter to keep current): ").strip().lower()
                rate_map = {"1": "-20%", "2": "-10%", "3": "+0%", "4": "+10%"}
                if rate_sel in rate_map:
                    rate = rate_map[rate_sel]
                elif rate_sel == "c":
                    val = input("Enter rate (e.g. -15% or +5%): ").strip()
                    if val:
                        rate = val if "%" in val else f"{val}%"

                ui.print_info(f"Updated tuning: Rate={rate}, Pitch={pitch}")
                synthesize_and_play("Testing the pitch and speed calibration. How does this gargoyle sound?", voice, rate, pitch, player)

            elif choice == "5":
                lang = input("Enter language code prefix (default: en): ").strip() or "en"
                list_voices(lang)
                v_name = input("\nEnter exact voice name to use (or Enter to cancel): ").strip()
                if v_name:
                    voice = v_name
                    ui.print_info(f"Switched voice to {voice}.")
                    synthesize_and_play("Hello! I am your new Halloween voice. Hear my call!", voice, rate, pitch, player)

            elif choice == "6":
                # Save to .env
                updates = {
                    "TTS_VOICE": voice,
                    "TTS_RATE": rate,
                    "TTS_PITCH": pitch
                }
                if update_env(ENV_PATH, updates):
                    ui.print_success(f"Saved new voice configuration to {ENV_PATH.name}!")
                    ui.print_info("Halloween Doorcam will now use this voice on its next run.")

            elif choice == "7":
                clear_audio_cache()

        except (KeyboardInterrupt, EOFError):
            print()
            ui.print_info("Exiting voice tester.")
            break


def main() -> None:
    """
    Main entry point for the Halloween Doorcam Voice & Sound Tester CLI.

    Parses command-line arguments to test custom phrases, audition specific voice models,
    adjust rate/pitch, audition pre-configured spooky presets, list available voices,
    or write modifications to `.env`. Launches `interactive_menu()` if run without flags.

    CLI Options:
      --text, -t <phrase>: Text phrase to synthesize and play immediately.
      --voice, -v <id>: Edge-TTS voice identifier (e.g. en-GB-RyanNeural).
      --rate, -r <rate>: Speaking speed percentage (e.g. -10%).
      --pitch, -p <pitch>: Pitch offset in Hz (e.g. -15Hz).
      --preset <id>: Pre-defined spooky preset ID to test.
      --list-voices: Display available voices matching --lang.
      --lang <prefix>: Filter language prefix for voice list (default: en).
      --save: Commit the specified voice parameters to .env.
      --clear-cache: Remove all cached dialogue files and exit.
      --warm-cache: Pre-generate common dialogue files and exit.

    Returns:
        None

    Example:
        $ ./test_voice.py --text "Happy Halloween!" --pitch -20Hz
    """
    parser = argparse.ArgumentParser(
        description="🎃 Halloween Doorcam Voice & Sound Tester",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  Interactive menu:
    ./test_voice.py

  Quick phrase test:
    ./test_voice.py --text "Welcome to the haunted house!"

  Test specific voice and pitch:
    ./test_voice.py --voice en-US-ChristopherNeural --pitch -22Hz --rate -15%

  Test preset directly:
    ./test_voice.py --preset deep_phantom_us

  Save test settings to .env:
    ./test_voice.py --voice en-US-ChristopherNeural --pitch -20Hz --save
"""
    )
    parser.add_argument("--text", "-t", type=str, help="Text phrase to synthesize and play")
    parser.add_argument("--voice", "-v", type=str, help="Edge-TTS voice identifier (e.g. en-GB-RyanNeural)")
    parser.add_argument("--rate", "-r", type=str, help="Speaking rate offset (e.g. -10%%, 0%%)")
    parser.add_argument("--pitch", "-p", type=str, help="Pitch offset (e.g. -15Hz, -20Hz)")
    parser.add_argument("--preset", type=str, choices=[p["id"] for p in SPOOKY_PRESETS], help="Audition a specific spooky preset by ID")
    parser.add_argument("--list-voices", action="store_true", help="List available Edge-TTS voices and exit")
    parser.add_argument("--lang", type=str, default="en", help="Language code filter for --list-voices (default: en)")
    parser.add_argument("--save", action="store_true", help="Save the provided or auditioned voice settings to .env")
    parser.add_argument("--clear-cache", action="store_true", help="Clear all cached audio files in audio_cache/ and exit")
    parser.add_argument("--warm-cache", action="store_true", help="Pre-generate common doorcam dialogues to cache and exit")

    args = parser.parse_args()

    if args.clear_cache:
        clear_audio_cache()
        return

    current_env = read_env(ENV_PATH)

    if args.list_voices:
        list_voices(args.lang)
        return

    # Check if CLI direct invocation was requested
    if args.preset:
        preset_data = next(p for p in SPOOKY_PRESETS if p["id"] == args.preset)
        voice = preset_data["voice"]
        rate = preset_data["rate"]
        pitch = preset_data["pitch"]
        text = args.text or preset_data["sample"]
    else:
        voice = args.voice or current_env.get("TTS_VOICE", "en-GB-RyanNeural")
        rate = args.rate or current_env.get("TTS_RATE", "-10%")
        pitch = args.pitch or current_env.get("TTS_PITCH", "-15Hz")
        text = args.text

    if text or args.voice or args.preset or args.rate or args.pitch:
        sample_text = text or "Welcome, foolish mortal! Answer my riddle, or face the darkness!"
        ui.print_section(f"Voice Preview: {voice}")
        success = synthesize_and_play(sample_text, voice, rate, pitch)

        if args.save and success:
            updates = {
                "TTS_VOICE": voice,
                "TTS_RATE": rate,
                "TTS_PITCH": pitch
            }
            if update_env(ENV_PATH, updates):
                ui.print_success(f"Saved configuration to {ENV_PATH.name}!")
        return

    # Otherwise launch interactive menu
    interactive_menu(current_env)


if __name__ == "__main__":
    main()
