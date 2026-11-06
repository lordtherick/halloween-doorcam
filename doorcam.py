#!/usr/bin/env python3
"""
💀 Halloween Doorcam - Interactive AI Skeleton Trick-or-Treat Sentinel
======================================================================
Autonomous Halloween doorstep skeleton sentinel that watches for approaching trick-or-treaters
via webcam motion detection, awakens with atmospheric sound effects, generates playful
Halloween riddles using a local Ollama LLM, listens and transcribes children's answers
using OpenAI Whisper, and judges their answers to reward candy or playfully tease them.

System Architecture:
--------------------
1. Motion Detection:
   - Headless background subtraction (frame differencing + contour analysis via OpenCV).
   - Cooldown period and frame-buffer flushing post-interaction to avoid feedback loops.
2. Spooky Audio FX & Atmosphere:
   - Plays atmospheric stingers (skeleton awakening, gothic bells, magical treasure chimes,
     dungeon failure gongs, haunted winds) using `spooky_fx.py`.
3. Speech Synthesis (TTS):
   - High-quality British or American skeleton voices via Microsoft Edge-TTS.
   - Deterministic SHA-256 disk caching to provide instantaneous audio playback.
4. Speech Recognition (STT):
   - PyAudio microphone capture with ambient noise calibration and energy threshold clamps.
   - Automatic gain normalization (up to +14dB boost) for quiet children's voices.
   - OpenAI Whisper speech-to-text with Halloween riddle vocabulary priming.
5. Large Language Model (LLM):
   - Ollama (e.g. Llama 3) for dynamic riddle generation and generous answer evaluation.
"""

import os
import re
import sys
import time
import random
import hashlib
import argparse
import subprocess
import wave
import difflib
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import numpy as np
except ImportError:
    np = None

try:
    import cv2
except ImportError:
    cv2 = None

try:
    import speech_recognition as sr
except ImportError:
    sr = None

try:
    import whisper
except ImportError:
    whisper = None

try:
    from ollama import Client
except ImportError:
    Client = None

try:
    from spooky_fx import play_sound_effect, prewarm_sound_effects
except ImportError:
    play_sound_effect = None
    prewarm_sound_effects = None

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv():
        pass


@contextmanager
def suppress_c_stderr():
    """
    Context manager to suppress low-level C library stderr output.

    PortAudio, ALSA, and JACK drivers print extensive diagnostic and probing
    warnings directly to the file descriptor 2 (stderr) during device enumeration.
    This context manager redirects file descriptor 2 to `/dev/null` at the OS
    kernel level and restores it upon exit.

    Yields:
        None

    Example:
        >>> with suppress_c_stderr():
        ...     mics = sr.Microphone.list_microphone_names()
    """
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        old_stderr = os.dup(2)
        sys.stderr.flush()
        os.dup2(devnull, 2)
        os.close(devnull)
        yield
    except Exception:
        yield
    finally:
        try:
            os.dup2(old_stderr, 2)
            os.close(old_stderr)
        except Exception:
            pass


# Load environment variables from .env file if present
load_dotenv()

# --- Hardware & Network Configuration ---
CAMERA_DEVICE = os.getenv("CAMERA_DEVICE", "/dev/video2")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://host.docker.internal:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")
WHISPER_MODEL_NAME = os.getenv("WHISPER_MODEL", "base")

# --- Edge-TTS Voice & Pitch Settings ---
TTS_VOICE = os.getenv("TTS_VOICE", "en-GB-RyanNeural")
TTS_RATE = os.getenv("TTS_RATE", "-10%")
TTS_PITCH = os.getenv("TTS_PITCH", "-15Hz")

# --- Video Motion Detection Settings ---
MOTION_THRESHOLD = int(os.getenv("MOTION_THRESHOLD", "5000"))
MOTION_COOLDOWN = int(os.getenv("MOTION_COOLDOWN", "15"))
MOTION_LOG_INTERVAL = float(os.getenv("MOTION_LOG_INTERVAL", "2.0"))
SAVE_DETECTED_FRAMES = os.getenv("SAVE_DETECTED_FRAMES", "true").lower() in ("true", "1", "yes")
DETECTED_FRAMES_DIR = Path(os.getenv("DETECTED_FRAMES_DIR", "detected_frames"))

# --- Speech Recognition Timing & Sensitivity ---
AMBIENT_NOISE_DURATION = float(os.getenv("AMBIENT_NOISE_DURATION", "0.8"))
LISTEN_TIMEOUT = int(os.getenv("LISTEN_TIMEOUT", "8"))
LISTEN_PHRASE_TIME_LIMIT = int(os.getenv("LISTEN_PHRASE_TIME_LIMIT", "15"))
PAUSE_THRESHOLD = float(os.getenv("PAUSE_THRESHOLD", "2.0"))
ENERGY_THRESHOLD = int(os.getenv("ENERGY_THRESHOLD", "300"))
DYNAMIC_ENERGY_THRESHOLD = os.getenv("DYNAMIC_ENERGY_THRESHOLD", "false").lower() in ("true", "1", "yes")
PRE_LISTEN_DELAY = float(os.getenv("PRE_LISTEN_DELAY", "0.2"))

# --- Script Paths & Riddles Configuration ---
SCRIPT_DIR = Path(__file__).resolve().parent
RIDDLES_FILE = Path(os.getenv("RIDDLES_FILE", SCRIPT_DIR / "riddles.txt"))
GREETINGS_FILE = Path(os.getenv("GREETINGS_FILE", SCRIPT_DIR / "greetings.txt"))

DEFAULT_GREETINGS: List[str] = [
    "Clickity-clack! Welcome, foolish mortals, to my haunted boneyard! Answer this skeleton's riddle if you dare!",
    "Rattle, rattle! Halt! Who goes there? Before you take a sweet, you must solve my spooky skeleton riddle!",
    "Happy Halloween, brave trick-or-treaters! Answer my bony riddle, and the candy is yours!",
    "Clack, clack, clack! Welcome to my crypt, little monsters! Let us see if you can solve this skeleton's Halloween riddle!",
    "Greetings, creatures of the night! My old bones are rattling for a puzzle... heed my riddle!",
    "Well shiver my ribs! Fresh souls approach! Solve my riddle if you wish to taste the candy within!",
    "Welcome, ghosts and ghouls! Do not trip over my funny bone! Listen closely to my riddle to earn your sweet reward!",
    "Who dares rattle the skeleton guardian of the treat bowl? Answer my riddle to pass!",
    "Happy Halloween, wanderers of the dark! Answer this old skeleton's riddle, or face a frightful trick!",
    "Beware, little goblins! Solve the riddle inside my hollow skull, and sweet treasures shall be yours!"
]

DEFAULT_RIDDLES: List[Dict[str, str]] = [
    {
        "question": "I have no flesh, no feathers, no scales, and no bone. Yet I have fingers and thumbs of my own. What am I?",
        "answer": "A glove"
    },
    {
        "question": "I have bones, but no flesh or skin. I rattle and clatter when I dance in the wind. What am I?",
        "answer": "A skeleton"
    },
    {
        "question": "I am carved with a scary grin, and I glow with a candle from within. What am I?",
        "answer": "A jack-o'-lantern"
    },
    {
        "question": "I fly on a broomstick, wear a pointy black hat, and brew bubbling potions with my black cat. Who am I?",
        "answer": "A witch"
    },
    {
        "question": "I am wrapped in white bandages from my head to my toes, asleep in a pyramid where the desert wind blows. Who am I?",
        "answer": "A mummy"
    },
    {
        "question": "I say \"Boo!\" and float through walls, but I am friendly when darkness falls. What am I?",
        "answer": "A ghost"
    },
    {
        "question": "I have eight hairy legs and spin silky webs in dusty dark corners. What am I?",
        "answer": "A spider"
    },
    {
        "question": "I wear a dark cape, sleep in a coffin by day, and turn into a bat to fly away. Who am I?",
        "answer": "A vampire"
    },
    {
        "question": "I fly without wings, howl without a mouth, and rattle the windows on Halloween night. What am I?",
        "answer": "The wind"
    },
    {
        "question": "I am tall when I am young, and short when I am old. I flicker in the dark on Halloween night. What am I?",
        "answer": "A candle"
    },
    {
        "question": "I have a head and a tail, but no body or legs. What am I?",
        "answer": "A coin"
    },
    {
        "question": "What has a spine, but no bones, and tells spooky stories when opened?",
        "answer": "A book"
    },
    {
        "question": "I only come out at night, I change my shape in the sky, and wolves howl at me as I pass by. What am I?",
        "answer": "The moon"
    },
    {
        "question": "I am made of bones, I protect your brain, and on Halloween I smile with no pain. What am I?",
        "answer": "A skull"
    },
    {
        "question": "What room do ghosts avoid because it has no walls?",
        "answer": "A mushroom"
    }
]


def clean_markdown_and_numbering(text: str) -> str:
    """
    Remove leading numbering (e.g. '1. ') and markdown symbols (**, *, __, _) from text.
    """
    text = re.sub(r'^\s*\d+[\.\)]\s*', '', text)
    text = text.replace('**', '').replace('__', '')
    text = text.replace('*', '').replace('_', '')
    return text.strip()


def clean_answer(ans: str) -> str:
    """
    Clean markdown formatting, surrounding quotes, and trailing punctuation from riddle answers.
    """
    ans = clean_markdown_and_numbering(ans)
    ans = ans.strip(' "\'“”‘’')
    ans = ans.rstrip('.! ')
    ans = ans.strip(' "\'“”‘’')
    return ans


def parse_riddle_line(line: str) -> Optional[Tuple[str, str]]:
    """
    Parse a single line from riddles.txt into a (question, answer) tuple.
    Supports:
      - '1. **Question?** Answer!'
      - 'Question | Answer'
      - 'Q: Question? / A: Answer'
      - 'Question? - Answer'
      - 'Question? Answer'
    """
    line = line.strip()
    if not line or line.startswith("#") or line.startswith("//"):
        return None

    # Markdown bold question format: '1. **What is it?** It is...'
    m = re.match(r'^(?:\d+[\.\)]\s*)?\*\*(.*?)\*\*\s*(.*)$', line)
    if m:
        q_raw, a_raw = m.group(1).strip(), m.group(2).strip()
        q = clean_markdown_and_numbering(q_raw)
        a = clean_answer(a_raw)
        if q and a:
            if not q.endswith("?"):
                q += "?"
            return q, a

    # Pipe delimiter: "Question | Answer"
    if "|" in line:
        parts = line.split("|", 1)
        q = clean_markdown_and_numbering(parts[0])
        a = clean_answer(parts[1])
        if q and a:
            return q, a

    # Colon/Dash with explicit Answer: tag
    match = re.split(r'\s*(?:Answer:|A:)\s*', line, maxsplit=1, flags=re.IGNORECASE)
    if len(match) == 2 and match[0].strip() and match[1].strip():
        q = clean_markdown_and_numbering(match[0])
        a = clean_answer(match[1])
        return q, a

    # Question followed by dash/colon separator: 'What am I? - A ghost'
    match = re.split(r'\?\s*[-:]\s*', line, maxsplit=1)
    if len(match) == 2 and match[0].strip() and match[1].strip():
        q = clean_markdown_and_numbering(match[0]) + "?"
        a = clean_answer(match[1])
        return q, a

    # Question ending in '?' with answer directly after: 'What am I? A ghost'
    if "?" in line and not line.endswith("?"):
        q_raw, a_raw = line.rsplit("?", 1)
        q = clean_markdown_and_numbering(q_raw) + "?"
        a = clean_answer(a_raw)
        if q and a:
            return q, a

    return None


def load_riddles(file_path: Optional[Path] = None) -> List[Dict[str, str]]:
    """
    Load Halloween riddles from riddles.txt with support for both single-line
    and multi-line Q&A formats, falling back to DEFAULT_RIDDLES if file is missing.
    """
    path = file_path or RIDDLES_FILE
    riddles: List[Dict[str, str]] = []

    if path.exists() and path.stat().st_size > 0:
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            current_q = None
            for raw_line in lines:
                line = raw_line.strip()
                if not line or line.startswith("#") or line.startswith("//"):
                    continue

                parsed = parse_riddle_line(line)
                if parsed:
                    riddles.append({"question": parsed[0], "answer": parsed[1]})
                    current_q = None
                    continue

                # Multi-line format: Q: ... / A: ...
                if re.match(r'^(?:Q:|Question:)\s*', line, flags=re.IGNORECASE):
                    current_q = re.sub(r'^(?:Q:|Question:)\s*', '', line, flags=re.IGNORECASE).strip()
                elif current_q and re.match(r'^(?:A:|Answer:)\s*', line, flags=re.IGNORECASE):
                    ans = re.sub(r'^(?:A:|Answer:)\s*', '', line, flags=re.IGNORECASE).strip()
                    riddles.append({"question": current_q, "answer": ans})
                    current_q = None
                elif not current_q and line.endswith("?"):
                    current_q = line
                elif current_q and not line.endswith("?"):
                    riddles.append({"question": current_q, "answer": line})
                    current_q = None
        except Exception as e:
            print(f"Warning: Could not read riddles from {path}: {e}")

    if not riddles:
        riddles = list(DEFAULT_RIDDLES)

    return riddles


_riddle_deck: List[Dict[str, str]] = []
_last_riddles_mtime: float = 0.0


def get_next_riddle() -> Dict[str, str]:
    """
    Retrieve the next riddle using a non-repeating shuffle deck.
    Randomly selects across all riddles in riddles.txt, automatically
    reloading if the file is modified on disk.
    """
    global _riddle_deck, _last_riddles_mtime
    file_mtime = RIDDLES_FILE.stat().st_mtime if RIDDLES_FILE.exists() else 0.0

    # Reload deck if empty or if riddles.txt was edited on disk
    if not _riddle_deck or file_mtime > _last_riddles_mtime:
        loaded = load_riddles()
        _riddle_deck = list(loaded)
        random.shuffle(_riddle_deck)
        _last_riddles_mtime = file_mtime

    return _riddle_deck.pop()


def load_greetings(file_path: Optional[Path] = None) -> List[str]:
    """
    Load Halloween greetings from greetings.txt, falling back to DEFAULT_GREETINGS.
    """
    path = file_path or GREETINGS_FILE
    greetings: List[str] = []
    if path.exists() and path.stat().st_size > 0:
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith(("#", "//")):
                        greetings.append(line)
        except Exception as e:
            print(f"Warning: Could not read greetings from {path}: {e}")

    if not greetings:
        greetings = list(DEFAULT_GREETINGS)
    return greetings


_greetings_deck: List[str] = []
_last_greetings_mtime: float = 0.0


def get_next_greeting() -> str:
    """
    Retrieve the next Halloween greeting using a non-repeating shuffle deck.
    Randomly selects across greetings, automatically reloading if greetings.txt
    is edited on disk.
    """
    global _greetings_deck, _last_greetings_mtime
    file_mtime = GREETINGS_FILE.stat().st_mtime if GREETINGS_FILE.exists() else 0.0

    if not _greetings_deck or file_mtime > _last_greetings_mtime:
        loaded = load_greetings()
        _greetings_deck = list(loaded)
        random.shuffle(_greetings_deck)
        _last_greetings_mtime = file_mtime

    return _greetings_deck.pop()


def format_failure_message(template: str, answer: str) -> str:
    """
    Format the failure message with the riddle answer and ensure scary costumes/sweets are credited.
    """
    ans_display = clean_answer(answer)
    if ans_display and len(ans_display) > 1 and not ans_display.isupper():
        if ans_display.lower().startswith(("a ", "an ", "the ")):
            ans_display = ans_display[0].lower() + ans_display[1:]

    if "{answer}" in template:
        return template.format(answer=ans_display)

    return f"{template} The answer was {ans_display}. But because you wear such a scary costume, you may take a sweet from the bowl anyway!"


# --- Dialogue & Costume Reward Prompts ---
CORRECT_ANSWER_MESSAGE = os.getenv(
    "CORRECT_ANSWER_MESSAGE",
    "Clickity-clack! You are clever, mortal! You tickled my funny bone—you may take a sweet from the bowl!"
)
DEFAULT_WRONG_ANSWER = "Rattle my ribs, not quite! The answer was {answer}. But because you wear such a scary costume, you may take a sweet from the bowl anyway!"
DEFAULT_GIVE_UP_ANSWER = "Stumped your hollow skull, did I? Clickity-clack! The answer was {answer}. Because you wear such a scary costume, you may take a sweet from the bowl anyway!"
DEFAULT_SILENT_ANSWER = "Cat got your tongue, or did my rattling bones scare you? The answer was {answer}. Because you wear such a scary costume, you may take a sweet from the bowl!"

_raw_wrong = os.getenv("WRONG_ANSWER_MESSAGE", DEFAULT_WRONG_ANSWER)
if "hidden in the shadows" in _raw_wrong:
    WRONG_ANSWER_TEMPLATE = DEFAULT_WRONG_ANSWER
else:
    WRONG_ANSWER_TEMPLATE = _raw_wrong

GIVE_UP_ANSWER_TEMPLATE = os.getenv("GIVE_UP_ANSWER_MESSAGE", DEFAULT_GIVE_UP_ANSWER)

_raw_silent = os.getenv("SILENT_ANSWER_MESSAGE", DEFAULT_SILENT_ANSWER)
if "no sweets for ghosts" in _raw_silent:
    SILENT_ANSWER_TEMPLATE = DEFAULT_SILENT_ANSWER
else:
    SILENT_ANSWER_TEMPLATE = _raw_silent

# --- Audio Cache & Hardware Routing ---
AUDIO_OUTPUT_DEVICE = os.getenv("AUDIO_OUTPUT_DEVICE")
AUDIO_INPUT_DEVICE = os.getenv("AUDIO_INPUT_DEVICE")
PULSE_SERVER = os.getenv("PULSE_SERVER")
MIC_DEVICE_INDEX = os.getenv("MIC_DEVICE_INDEX")
AUDIO_CACHE_DIR = Path(os.getenv("AUDIO_CACHE_DIR", "audio_cache"))
AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# --- Spooky Sound Effects Configuration ---
ENABLE_SOUND_EFFECTS = os.getenv("ENABLE_SOUND_EFFECTS", "true").lower() in ("true", "1", "yes")
FX_MOTION_DETECTED = os.getenv("FX_MOTION_DETECTED", "motion_detected")
FX_RIDDLE_INTRO = os.getenv("FX_RIDDLE_INTRO", "riddle_intro")
FX_CORRECT_ANSWER = os.getenv("FX_CORRECT_ANSWER", "correct_answer")
FX_WRONG_ANSWER = os.getenv("FX_WRONG_ANSWER", "wrong_answer")
FX_SILENT_ANSWER = os.getenv("FX_SILENT_ANSWER", "silence_ghost")


def find_microphone_index(target_name: str) -> Tuple[Optional[int], str]:
    """
    Locate the PyAudio device index matching the configured microphone name or keywords.

    Searches available PyAudio input devices using a three-tier matching heuristic:
      1. Exact or substring match against device names.
      2. Multi-keyword match (e.g. matching both 'wireless' and 'microphone' inside
         'Wireless Microphone: USB Audio (hw:2,0)').
      3. Any keyword presence as fallback.

    Args:
        target_name (str): Device name, description, or keyword configured in .env.

    Returns:
        Tuple[Optional[int], str]:
            - Device integer index (or None if default system mic should be used).
            - Friendly display name of the resolved device.

    Example:
        >>> idx, name = find_microphone_index("Wireless Microphone")
        >>> print(idx, name)
        5, 'Wireless Microphone: USB Audio (hw:2,0)'
    """
    if not target_name or target_name.lower() in ("default", "none", ""):
        return None, "Default System Microphone"
    try:
        with suppress_c_stderr():
            mic_names = sr.Microphone.list_microphone_names() if sr else []
        if not mic_names:
            return None, target_name

        # Clean target string: remove common bus/stream suffixes
        clean_target = re.sub(
            r"(?i)\b(analog|digital|stereo|mono|multichannel|capture|source|sink|input|output)\b",
            "",
            target_name
        )
        target_words = [w.lower() for w in re.findall(r"\w+", clean_target) if len(w) > 2]

        # 1. Exact or substring match
        for idx, name in enumerate(mic_names):
            if target_name.lower() in name.lower() or name.lower() in target_name.lower():
                return idx, name

        # 2. All keywords present
        if target_words:
            for idx, name in enumerate(mic_names):
                nl = name.lower()
                if all(w in nl for w in target_words):
                    return idx, name

        # 3. Any keyword present fallback
        if target_words:
            for idx, name in enumerate(mic_names):
                nl = name.lower()
                if any(w in nl for w in target_words):
                    return idx, name
    except Exception as e:
        print(f"Error enumerating microphones: {e}")
    return None, target_name


def normalize_audio(wav_path: str, target_peak: float = 0.90) -> None:
    """
    Amplify and normalize low-amplitude recorded speech for Whisper transcription.

    Reads a recorded 16-bit or 32-bit PCM WAV file. If the maximum absolute peak
    sample is below 70% of full-scale amplitude, calculates a linear gain multiplier
    (capped at 5.0x / +14dB) to scale the waveform up to `target_peak` and rewrites
    the file with clipping protection.

    Args:
        wav_path (str): Path to the WAV audio file recorded from the microphone.
        target_peak (float): Target peak amplitude fraction [0.0 - 1.0]. Defaults to 0.90.

    Returns:
        None

    Example:
        >>> normalize_audio("temp_mic.wav")
        # Audio is now cleanly amplified for Whisper speech recognition
    """
    if np is None:
        return
    try:
        with wave.open(wav_path, "rb") as wf:
            params = wf.getparams()
            frames = wf.readframes(params.nframes)
        if not frames:
            return
        dtype = np.int16 if params.sampwidth == 2 else np.int32
        data = np.frombuffer(frames, dtype=dtype).astype(np.float32)
        max_val = float(np.iinfo(dtype).max)
        peak = float(np.max(np.abs(data)))
        # Only normalize if there is genuine audio (> 2% full scale) to avoid amplifying silence/noise
        if peak > (max_val * 0.02) and (peak / max_val) < 0.70:
            scale = min((target_peak * max_val) / peak, 4.0)  # Up to +12dB clean gain boost
            data = np.clip(data * scale, -max_val, max_val).astype(dtype)
            with wave.open(wav_path, "wb") as wf:
                wf.setparams(params)
                wf.writeframes(data.tobytes())
    except Exception as e:
        print(f"Audio normalization notice: {e}")


# Global ML model and hardware singletons (initialized on startup in init_ml_models)
ollama_client = None
MODEL = OLLAMA_MODEL
whisper_model = None
recognizer = None
_cached_mic_idx = None
_cached_mic_name = "System Default"
_mic_calibrated = False


def init_ml_models() -> None:
    """
    Initialize and pre-load machine learning models into memory, resolve microphone,
    and calibrate ambient noise.

    Connects to the Ollama server for riddle evaluation and loads the OpenAI
    Whisper speech-to-text model on the CPU/GPU. Doing this during startup avoids
    delays during trick-or-treater interactions.
    """
    global ollama_client, whisper_model, recognizer, MODEL
    global _cached_mic_idx, _cached_mic_name, _mic_calibrated

    if ollama_client is None and Client:
        hosts_to_try = [OLLAMA_HOST]
        if "host.docker.internal" in OLLAMA_HOST:
            hosts_to_try.append("http://localhost:11434")
        elif "localhost" in OLLAMA_HOST or "127.0.0.1" in OLLAMA_HOST:
            hosts_to_try.append("http://host.docker.internal:11434")

        for h in hosts_to_try:
            try:
                candidate = Client(host=h)
                candidate.tags()
                ollama_client = candidate
                MODEL = OLLAMA_MODEL
                print(f"Connected to Ollama at: {h} (Model: {MODEL})")
                break
            except Exception:
                continue

        if ollama_client is None:
            print(f"Notice: Could not connect to Ollama at {hosts_to_try}. Rule-based evaluation will be used.")

    if whisper_model is None and whisper:
        print(f"Loading Whisper model '{WHISPER_MODEL_NAME}'...")
        whisper_model = whisper.load_model(WHISPER_MODEL_NAME)
        recognizer = sr.Recognizer()

    # Pre-resolve microphone device once at startup
    if _cached_mic_idx is None:
        idx = int(MIC_DEVICE_INDEX) if (MIC_DEVICE_INDEX and MIC_DEVICE_INDEX.isdigit()) else None
        name = "System Default"
        if idx is None:
            idx, name = find_microphone_index(AUDIO_INPUT_DEVICE)
        elif sr:
            with suppress_c_stderr():
                names = sr.Microphone.list_microphone_names()
                if 0 <= idx < len(names):
                    name = names[idx]
        _cached_mic_idx = idx
        _cached_mic_name = name
        print(f"Resolved microphone: [{_cached_mic_idx}] {_cached_mic_name}")

    # Pre-calibrate ambient background noise once at startup
    if sr and recognizer and not _mic_calibrated and AMBIENT_NOISE_DURATION > 0:
        try:
            print(f"Pre-calibrating ambient background noise ({AMBIENT_NOISE_DURATION}s)...")
            with suppress_c_stderr():
                with sr.Microphone(device_index=_cached_mic_idx) as source:
                    recognizer.adjust_for_ambient_noise(source, duration=AMBIENT_NOISE_DURATION)
                    if ENERGY_THRESHOLD > 0:
                        recognizer.energy_threshold = min(max(recognizer.energy_threshold, 150), max(ENERGY_THRESHOLD, 600))
                    else:
                        recognizer.energy_threshold = min(recognizer.energy_threshold, 600)
            _mic_calibrated = True
            print(f"Calibrated microphone energy threshold: {int(recognizer.energy_threshold)}")
        except Exception as e:
            print(f"Notice: Initial ambient noise calibration skipped ({e})")


def get_cached_audio_path(text: str, voice: str = None, rate: str = None, pitch: str = None) -> Path:
    """
    Generate a deterministic filesystem path for caching synthesized speech audio.

    Creates a SHA-256 hash digest of the combined voice parameters and text content,
    ensuring that if voice tuning (rate, pitch, or voice model) changes in `.env`,
    stale audio is automatically bypassed and freshly synthesized.

    Args:
        text (str): Dialogue phrase to synthesize.
        voice (str, optional): TTS voice ID. Defaults to configured TTS_VOICE.
        rate (str, optional): Speech rate adjustment. Defaults to configured TTS_RATE.
        pitch (str, optional): Voice pitch adjustment. Defaults to configured TTS_PITCH.

    Returns:
        Path: Pathlib object representing the destination MP3 file in `audio_cache/`.

    Example:
        >>> path = get_cached_audio_path("Welcome to my doorstep!")
        >>> print(path.name)
        welcome_to_my_door_7a9f82d41b0e.mp3
    """
    v = voice or TTS_VOICE
    r = rate or TTS_RATE
    p = pitch or TTS_PITCH
    hash_payload = f"{v}|{r}|{p}|{text.strip()}".encode("utf-8")
    content_hash = hashlib.sha256(hash_payload).hexdigest()[:12]
    slug = re.sub(r'[^a-zA-Z0-9]+', '_', text[:20]).strip('_').lower() or "voice"
    return AUDIO_CACHE_DIR / f"{slug}_{content_hash}.mp3"


def clear_audio_cache() -> int:
    """
    Remove all cached MP3 dialogue audio files from disk.

    Deletes all `.mp3` files located directly within `AUDIO_CACHE_DIR` to free
    disk space or force re-synthesis of dialogue files.

    Returns:
        int: Number of audio cache files deleted.

    Example:
        >>> deleted = clear_audio_cache()
        >>> print(f"Deleted {deleted} cached files.")
    """
    if not AUDIO_CACHE_DIR.exists():
        print(f"Cache directory '{AUDIO_CACHE_DIR}' does not exist.")
        return 0

    deleted_count = 0
    total_bytes = 0
    for file_path in AUDIO_CACHE_DIR.glob("*.mp3"):
        try:
            total_bytes += file_path.stat().st_size
            file_path.unlink()
            deleted_count += 1
        except Exception as e:
            print(f"Error removing {file_path.name}: {e}")

    size_kb = total_bytes / 1024.0
    print(f"Audio cache cleared: removed {deleted_count} file(s) ({size_kb:.1f} KB freed).")
    return deleted_count


def warm_single_phrase(phrase: str) -> Tuple[str, bool]:
    """
    Synthesize and cache a single dialogue phrase if not already cached.
    """
    audio_file = get_cached_audio_path(phrase)
    if audio_file.exists() and audio_file.stat().st_size > 0:
        return phrase, False

    temp_file = audio_file.with_suffix(".tmp.mp3")
    try:
        subprocess.run([
            "edge-tts",
            f"--voice={TTS_VOICE}",
            f"--rate={TTS_RATE}",
            f"--pitch={TTS_PITCH}",
            f"--text={phrase}",
            f"--write-media={str(temp_file)}"
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        temp_file.replace(audio_file)
        return phrase, True
    except Exception as e:
        if temp_file.exists():
            temp_file.unlink(missing_ok=True)
        return phrase, False


def warm_audio_cache() -> None:
    """
    Pre-synthesize all standard static dialogue lines, riddles from riddles.txt,
    and Halloween sound effects to eliminate network or synthesis latency during live interactions.

    Returns:
        None

    Example:
        >>> warm_audio_cache()
    """
    phrases = [
        CORRECT_ANSWER_MESSAGE,
    ]
    for g in load_greetings():
        if g not in phrases:
            phrases.append(g)

    riddles = load_riddles()
    for r in riddles:
        q = r["question"]
        if q not in phrases:
            phrases.append(q)
        w_msg = format_failure_message(WRONG_ANSWER_TEMPLATE, r["answer"])
        if w_msg not in phrases:
            phrases.append(w_msg)
        g_msg = format_failure_message(GIVE_UP_ANSWER_TEMPLATE, r["answer"])
        if g_msg not in phrases:
            phrases.append(g_msg)
        s_msg = format_failure_message(SILENT_ANSWER_TEMPLATE, r["answer"])
        if s_msg not in phrases:
            phrases.append(s_msg)

    total = len(phrases)
    print(f"Pre-warming audio cache ({total} dialogue phrases)...")

    cached_count = 0
    hit_count = 0

    # Process up to 5 concurrent Edge-TTS requests to speed up caching without overloading rate limits
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_phrase = {executor.submit(warm_single_phrase, p): p for p in phrases}
        for future in as_completed(future_to_phrase):
            phrase, was_generated = future.result()
            if was_generated:
                cached_count += 1
                slug = phrase[:35].strip()
                print(f"  [Generated {cached_count + hit_count}/{total}] \"{slug}...\"")
            else:
                hit_count += 1

    print(f"Audio cache pre-warm complete: {cached_count} freshly generated, {hit_count} already cached.")
    if ENABLE_SOUND_EFFECTS and prewarm_sound_effects:
        prewarm_sound_effects()


def speak(text: str) -> None:
    """
    Synthesize text into speech using Edge-TTS with caching and play via mpg123.

    Checks the disk cache for a pre-rendered MP3 file. On a cache miss, calls
    the `edge-tts` CLI tool to generate the audio. Routes playback through `mpg123`
    to the configured PulseAudio server or ALSA audio output device.

    Args:
        text (str): Natural language sentence or dialogue to speak.

    Returns:
        None

    Example:
        >>> speak("I am the watcher of the gate!")
    """
    if not text or not text.strip():
        return

    AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    audio_file = get_cached_audio_path(text)

    # Check if cached audio already exists and is non-empty
    if audio_file.exists() and audio_file.stat().st_size > 0:
        print(f"[Cache Hit] Playing cached audio: {audio_file.name}")
    else:
        print(f"[Cache Miss] Generating audio with edge-tts: {audio_file.name}...")
        temp_file = audio_file.with_suffix(".tmp.mp3")
        try:
            subprocess.run([
                "edge-tts",
                f"--voice={TTS_VOICE}",
                f"--rate={TTS_RATE}",
                f"--pitch={TTS_PITCH}",
                f"--text={text}",
                f"--write-media={str(temp_file)}"
            ], check=True)
            temp_file.replace(audio_file)
        except Exception as e:
            print(f"Error generating TTS audio: {e}")
            if temp_file.exists():
                temp_file.unlink(missing_ok=True)
            return

    # Configure mpg123 output module
    cmd = ["mpg123", "-q"]
    if PULSE_SERVER:
        cmd.extend(["-o", "pulse"])
    elif AUDIO_OUTPUT_DEVICE and AUDIO_OUTPUT_DEVICE.lower() not in ("default", "none"):
        cmd.extend(["-a", AUDIO_OUTPUT_DEVICE])
    cmd.append(str(audio_file))

    try:
        subprocess.run(cmd, check=True)
    except Exception as e:
        print(f"Error in audio playback: {e}")


# --- Robust Phonetic & Pun Answer Matching Engine ---
PUN_EQUIVALENTS = {
    'sandwich': ['sand witch', 'sandwitch', 'sandwich', 'sandwiches'],
    'sand witch': ['sand witch', 'sandwitch', 'sandwich', 'sandwiches'],
    'ice cream': ['i scream', 'iscream', 'ice cream', 'icecream'],
    'i scream': ['i scream', 'iscream', 'ice cream', 'icecream'],
    'coffin': ['coughing', 'cough', 'coughs', 'coffin'],
    'coughing': ['coughing', 'cough', 'coughs', 'coffin'],
    'rap': ['wrap', 'wrapped', 'rap music', 'wrap music', 'rap'],
    'wrap': ['wrap', 'wrapped', 'rap music', 'wrap music', 'rap'],
    'nobody': ['no body', 'nobody', 'no-body', 'body'],
    'no body': ['no body', 'nobody', 'no-body', 'body'],
    'frostbite': ['frost bite', 'frostbite', 'frost'],
    'frost bite': ['frost bite', 'frostbite', 'frost'],
    'website': ['web site', 'website', 'web'],
    'web site': ['web site', 'website', 'web'],
    'boots': ['boo-ts', 'boots'],
    'boo-ts': ['boo-ts', 'boots'],
    'galoshes': ['ghoul-oshes', 'ghouloshes', 'galoshes'],
    'ghoul-oshes': ['ghoul-oshes', 'ghouloshes', 'galoshes'],
    'ghouloshes': ['ghoul-oshes', 'ghouloshes', 'galoshes'],
    'cut it out': ['cut it out'],
    'see through': ['see through', 'transparent', 'see right through'],
    'dry witch': ['dry witch', 'sandwich', 'sand witch'],
    'trombone': ['trom bone', 'trombone', 'bone'],
    'girlfriend': ['ghoulfriend', 'ghoul friend', 'girlfriend', 'girl friend'],
    'ghoulfriend': ['ghoulfriend', 'ghoul friend', 'girlfriend', 'girl friend'],
    'grim reaper': ['grim sweeper', 'sweeper', 'grim reaper'],
    'grim sweeper': ['grim sweeper', 'sweeper', 'grim reaper'],
    'hair spray': ['scare spray', 'hair spray', 'hairspray'],
    'scare spray': ['scare spray', 'hair spray', 'hairspray'],
    'hide and seek': ['hide and shriek', 'hide and seek'],
    'hide and shriek': ['hide and shriek', 'hide and seek'],
    'post office': ['ghost office', 'post office'],
    'ghost office': ['ghost office', 'post office'],
    'hang out': ['hang around', 'hanging around', 'hang out', 'hanging out'],
    'hang around': ['hang around', 'hanging around', 'hang out', 'hanging out'],
    'nectarine': ['neck tarine', 'necktarine', 'nectarine'],
    'neck tarine': ['neck tarine', 'necktarine', 'nectarine'],
    'plumpkin': ['plumpkin', 'plump pumpkin', 'plump', 'pumpkin'],
    'plump kin': ['plumpkin', 'plump pumpkin', 'plump', 'pumpkin'],
    'horoscope': ['horror scope', 'horrorscope', 'horoscope'],
    'horror scope': ['horror scope', 'horrorscope', 'horoscope'],
    'transparent': ['trans parents', 'transparents', 'transparent', 'parents'],
    'trans parents': ['trans parents', 'transparents', 'transparent', 'parents'],
    'blueberries': ['boo berries', 'booberries', 'blueberries', 'blueberry'],
    'boo berries': ['boo berries', 'booberries', 'blueberries', 'blueberry'],
    'booberries': ['boo berries', 'booberries', 'blueberries', 'blueberry'],
    'cough drops': ['coffin drops', 'cough drops', 'cough drop', 'coffin drop'],
    'coffin drops': ['coffin drops', 'cough drops', 'cough drop', 'coffin drop'],
    'badminton': ['batminton', 'bat minton', 'badminton'],
    'batminton': ['batminton', 'bat minton', 'badminton'],
    'boomerang': ['boo meringue', 'boomeringue', 'meringue', 'boomerang', 'boomerange'],
    'boo meringue': ['boo meringue', 'boomeringue', 'meringue', 'boomerang', 'boomerange'],
    'bad breath': ['bat breath', 'bad breath'],
    'bat breath': ['bat breath', 'bad breath'],
    'girl scout': ['ghoul scout', 'girl scout'],
    'ghoul scout': ['ghoul scout', 'girl scout'],
    'jack o lantern': ['jack o lantern', 'jackolantern', 'pumpkin'],
    'jackolantern': ['jack o lantern', 'jackolantern', 'pumpkin'],
    'vampire': ['vampire', 'dracula'],
    'skeleton': ['skeleton', 'bones'],
    'skull': ['skull', 'bones'],
    'coin': ['coin', 'money', 'penny', 'cent'],
}

STOP_WORDS = {
    'a', 'an', 'the', 'he', 'she', 'it', 'they', 'we', 'i', 'you',
    'is', 'was', 'are', 'were', 'be', 'been', 'being',
    'to', 'of', 'for', 'at', 'by', 'from', 'with', 'in', 'on',
    'his', 'her', 'their', 'my', 'its', 'our', 'your',
    'because', 'all', 'just', 'that', 'this', 'and', 'or', 'but',
    'have', 'had', 'has', 'did', 'do', 'does', 'not', 'dont', 'go',
    'out', 'up', 'down', 'so', 'as', 'no'
}

GIVE_UP_PATTERNS = [
    r'\b(?:i\s+)?(?:do\s+not|don[\'t\s]*t|dont)\s+know\b',
    r'\bno\s+idea\b',
    r'\bnot\s+sure\b',
    r'\bdunno\b',
    r'\bi\s+give\s+up\b',
    r'\bgive\s+up\b',
    r'\bpass\b',
    r'\btrick\s+or\s+treat\b',
    r'\bwhat\b',
    r'\bhuh\b',
    r'\bcandy\b',
    r'\bhappy\s+halloween\b',
]


def clean_text_for_matching(text: str) -> str:
    """Normalize text by stripping quotes, markdown asterisks, and excessive punctuation."""
    t = text.lower()
    t = re.sub(r'[*_\"\'“”‘’`]', '', t)
    t = re.sub(r'[^a-z0-9\s-]', ' ', t)
    t = re.sub(r'\s+', ' ', t)
    return t.strip()


def is_give_up_answer(kid_answer: str) -> bool:
    """
    Check if the child's spoken response is an "I don't know", "give up", or filler phrase
    without containing an actual riddle answer guess.
    """
    clean_k = clean_text_for_matching(kid_answer)
    if not clean_k:
        return False

    for pat in GIVE_UP_PATTERNS:
        if re.search(pat, clean_k):
            words = [
                w for w in re.findall(r'[a-z0-9]+', clean_k)
                if w not in STOP_WORDS and w not in {
                    'know', 'idea', 'give', 'up', 'sure', 'dunno', 'trick', 'treat',
                    'pass', 'candy', 'happy', 'halloween', 'what', 'huh', 'please'
                }
            ]
            if not words:
                return True
    return False


def check_answer_match(expected: str, kid: str) -> bool:
    """
    Determine whether a child's spoken transcription matches the expected riddle answer
    via phonetic pun normalization, compact matching, and whole-word fuzzy token analysis.
    """
    clean_k = clean_text_for_matching(kid)
    clean_e = clean_text_for_matching(expected)
    if not clean_k or not clean_e:
        return False

    # 1. Fast check for give-up or filler phrases
    if is_give_up_answer(kid):
        return False

    # 2. Build target phrase set with pun and sound-alike variants
    target_phrases = set()
    e_no_hyphen = clean_e.replace('-', ' ')
    e_compact = clean_e.replace('-', '').replace(' ', '')
    k_compact = clean_k.replace('-', '').replace(' ', '')

    target_phrases.add(clean_e)
    target_phrases.add(e_no_hyphen)

    for k, v in PUN_EQUIVALENTS.items():
        k_clean = clean_text_for_matching(k)
        if k_clean in clean_e or k_clean in e_no_hyphen or k_clean.replace('-', '').replace(' ', '') in e_compact:
            for alt in v:
                target_phrases.add(clean_text_for_matching(alt))
                target_phrases.add(clean_text_for_matching(alt).replace('-', ' '))

    # 3. Compact string match (e.g., 'frostbite' vs 'frost bite', 'nobody' vs 'no body')
    for phrase in target_phrases:
        p_compact = phrase.replace('-', '').replace(' ', '')
        if len(p_compact) >= 4 and p_compact in k_compact:
            return True

    # 4. Whole-phrase regex match in spoken answer
    for phrase in target_phrases:
        if len(phrase) >= 3:
            pattern = r'\b' + re.escape(phrase) + r'\b'
            if re.search(pattern, clean_k) or re.search(pattern, clean_k.replace('-', ' ')):
                return True

    # 5. Significant word token overlap & fuzzy matching
    e_words = [
        w for w in re.findall(r'[a-z0-9]+', clean_e.replace('-', ' ') + ' ' + clean_e.replace('-', ''))
        if w not in STOP_WORDS
    ]
    k_words = [
        w for w in re.findall(r'[a-z0-9]+', clean_k.replace('-', ' ') + ' ' + clean_k.replace('-', ''))
        if w not in STOP_WORDS
    ]

    expanded_e_words = set(e_words)
    for phrase in target_phrases:
        for w in re.findall(r'[a-z0-9]+', phrase.replace('-', ' ') + ' ' + phrase.replace('-', '')):
            if w not in STOP_WORDS:
                expanded_e_words.add(w)

    for kw in k_words:
        if kw in expanded_e_words:
            return True
        for ew in expanded_e_words:
            if len(ew) >= 4 and len(kw) >= 4:
                if difflib.SequenceMatcher(None, kw, ew).ratio() >= 0.82:
                    return True

    return False


def evaluate_trick_or_treater_answer(riddle_question: str, riddle_answer: str, kid_answer: str) -> bool:
    """
    Intelligently evaluate trick-or-treater riddle answers using multi-tier matching:
      1. Give-up / filler phrase detection (e.g., 'I don't know', 'trick or treat' -> False).
      2. Fast phonetic & pun matching (handles puns, homophones, compound words, and sound-alikes).
      3. Strict LLM evaluation via Ollama fallback (temperature 0.0 with fail-safe parsing).
    """
    # 1. Immediate rejection of give-up phrases
    if is_give_up_answer(kid_answer):
        print(f"Result: Child gave up or spoke filler: '{kid_answer}'")
        return False

    # 2. Rule-based Phonetic & Pun Matching
    if check_answer_match(riddle_answer, kid_answer):
        print(f"Result: Match found via pun/keyword engine ('{kid_answer}' -> '{riddle_answer}')")
        return True

    # 3. Fallback to Ollama for nuanced answers
    if ollama_client:
        eval_prompt = (
            f"You are evaluating a child's spoken answer to a Halloween riddle.\n"
            f"Riddle: \"{riddle_question}\"\n"
            f"Expected Answer: \"{riddle_answer}\"\n"
            f"Child's Spoken Answer: \"{kid_answer}\"\n\n"
            f"Task: Determine if the child's answer is correct, a plausible synonym, or the pun punchline.\n"
            f"Rules:\n"
            f"- If the child said an unrelated word (e.g. \"banana\", \"car\", \"apple\") or gave up, answer INCORRECT.\n"
            f"- If the child understood the riddle or gave the correct punchline, answer CORRECT.\n"
            f"Reply with ONLY the word CORRECT or INCORRECT."
        )
        try:
            eval_response = ollama_client.generate(model=MODEL, prompt=eval_prompt, options={"temperature": 0.0})
            raw_eval = eval_response.get("response", "").strip()
            first_line = raw_eval.split("\n")[0].strip().upper()
            is_correct = "CORRECT" in first_line and "INCORRECT" not in first_line
            print(f"Ollama judgment: {first_line} -> {'CORRECT' if is_correct else 'WRONG'}")
            return is_correct
        except Exception as e:
            print(f"Notice: Ollama evaluation error: {e}")

    return False


def interact() -> None:
    """
    Execute the interactive trick-or-treat state machine when motion is triggered.

    Interaction Workflow:
      0. Motion Awakening Stinger: Plays the crypt gate grinding / awakening sound effect.
      1. Spooky Halloween Greeting: Greets the trick-or-treater with a random Halloween welcome.
      2. Riddle Announcement: Announces the riddle from riddles.txt accompanied by gothic bells.
      3. Seamless Speech Capture: Opens the microphone immediately after the riddle question finishes,
         recording the child's response with zero awkward delay.
      4. Accurate Evaluation & Reward: Accurately evaluates the response using the pun and phonetic
         engine, playing a winning chime and awarding sweets for correct answers, or playfully
         revealing the answer and awarding sweets for their scary costume.
    """
    # 0. Motion Awakening Stinger
    if ENABLE_SOUND_EFFECTS and play_sound_effect and FX_MOTION_DETECTED:
        play_sound_effect(FX_MOTION_DETECTED, pulse_server=PULSE_SERVER, audio_output_device=AUDIO_OUTPUT_DEVICE, wait=True)

    # 1. Spooky Halloween Skeleton Greeting
    greeting = get_next_greeting()
    print(f"\n💀 Skeleton Greeting: {greeting}")
    speak(greeting)

    # 2. Select and Ask Riddle from riddles.txt
    riddle_item = get_next_riddle()
    riddle_question = riddle_item["question"]
    riddle_answer = riddle_item["answer"]

    print(f"\n🦴 Skeleton Riddle: {riddle_question}")
    print(f"Expected Answer: {riddle_answer}")
    if ENABLE_SOUND_EFFECTS and play_sound_effect and FX_RIDDLE_INTRO:
        play_sound_effect(FX_RIDDLE_INTRO, pulse_server=PULSE_SERVER, audio_output_device=AUDIO_OUTPUT_DEVICE, wait=True)
    speak(riddle_question)

    # 3. Immediately Listen for Answer (seamless transition, no intermediate speech delay)
    if PRE_LISTEN_DELAY > 0:
        time.sleep(PRE_LISTEN_DELAY)

    print("🎤 Listening for answer...")
    kid_answer = ""

    mic_idx = _cached_mic_idx
    if mic_idx is not None:
        print(f"Microphone: [{mic_idx}] {_cached_mic_name}")

    with suppress_c_stderr():
        mic_context = sr.Microphone(device_index=mic_idx)
        with mic_context as source:
            if not _mic_calibrated and AMBIENT_NOISE_DURATION > 0:
                recognizer.adjust_for_ambient_noise(source, duration=min(AMBIENT_NOISE_DURATION, 0.3))
                if ENERGY_THRESHOLD > 0:
                    recognizer.energy_threshold = min(max(recognizer.energy_threshold, 150), max(ENERGY_THRESHOLD, 600))
                else:
                    recognizer.energy_threshold = min(recognizer.energy_threshold, 600)

            recognizer.dynamic_energy_threshold = DYNAMIC_ENERGY_THRESHOLD
            recognizer.pause_threshold = PAUSE_THRESHOLD
            recognizer.phrase_threshold = 0.2  # Trigger promptly on short kid answers
            recognizer.non_speaking_duration = 0.6

            print(f"Ready (energy threshold: {int(recognizer.energy_threshold)}). Speak now!")
            try:
                audio = recognizer.listen(source, timeout=LISTEN_TIMEOUT, phrase_time_limit=LISTEN_PHRASE_TIME_LIMIT)
                with open("temp_mic.wav", "wb") as f:
                    f.write(audio.get_wav_data())

                # Boost audio volume if recording is quiet
                normalize_audio("temp_mic.wav")

                # Transcribe with English language locking and anti-hallucination thresholds
                transcribe_out = whisper_model.transcribe(
                    "temp_mic.wav",
                    language="en",
                    fp16=False,
                    temperature=0.0,
                    condition_on_previous_text=False,
                    no_speech_threshold=0.6,
                    compression_ratio_threshold=2.2
                )
                raw_text = transcribe_out.get("text", "").strip()

                # Guard against Whisper hallucination loops on silence/low audio
                is_hallucination = False
                segments = transcribe_out.get("segments", [])
                if segments:
                    avg_no_speech = sum(s.get("no_speech_prob", 0) for s in segments) / len(segments)
                    if avg_no_speech > 0.65:
                        is_hallucination = True

                words = raw_text.lower().split()
                if len(words) > 8:
                    unique_ratio = len(set(words)) / len(words)
                    if unique_ratio < 0.40:  # Excessive repetition loop
                        is_hallucination = True

                if is_hallucination or not raw_text:
                    kid_answer = ""
                    print("No distinct speech detected (filtered silence/background noise).")
                else:
                    kid_answer = raw_text
                    print(f"Kid said: {kid_answer}")
            except sr.WaitTimeoutError:
                print("No audio detected.")
            except Exception as e:
                print(f"Microphone error: {e}")

    # 4. Evaluate Trick-or-Treater Answer
    if not kid_answer:
        print("Child did not speak in time.")
        if ENABLE_SOUND_EFFECTS and play_sound_effect and FX_SILENT_ANSWER:
            play_sound_effect(FX_SILENT_ANSWER, pulse_server=PULSE_SERVER, audio_output_device=AUDIO_OUTPUT_DEVICE, wait=True)
        silent_msg = format_failure_message(SILENT_ANSWER_TEMPLATE, riddle_answer)
        speak(silent_msg)
        return

    print(f"Evaluating answer: '{kid_answer}' (Target: '{riddle_answer}')...")
    if is_give_up_answer(kid_answer):
        print(f"Result: GIVE UP ('{kid_answer}'). Revealing answer '{riddle_answer}' with custom give-up response.")
        if ENABLE_SOUND_EFFECTS and play_sound_effect and FX_WRONG_ANSWER:
            play_sound_effect(FX_WRONG_ANSWER, pulse_server=PULSE_SERVER, audio_output_device=AUDIO_OUTPUT_DEVICE, wait=True)
        give_up_msg = format_failure_message(GIVE_UP_ANSWER_TEMPLATE, riddle_answer)
        speak(give_up_msg)
        return

    is_correct = evaluate_trick_or_treater_answer(riddle_question, riddle_answer, kid_answer)

    if is_correct:
        print("Result: CORRECT! Sweet earned.")
        if ENABLE_SOUND_EFFECTS and play_sound_effect and FX_CORRECT_ANSWER:
            play_sound_effect(FX_CORRECT_ANSWER, pulse_server=PULSE_SERVER, audio_output_device=AUDIO_OUTPUT_DEVICE, wait=True)
        speak(CORRECT_ANSWER_MESSAGE)
    else:
        print(f"Result: WRONG. Revealing answer '{riddle_answer}' and awarding sweet for scary costume.")
        if ENABLE_SOUND_EFFECTS and play_sound_effect and FX_WRONG_ANSWER:
            play_sound_effect(FX_WRONG_ANSWER, pulse_server=PULSE_SERVER, audio_output_device=AUDIO_OUTPUT_DEVICE, wait=True)
        wrong_msg = format_failure_message(WRONG_ANSWER_TEMPLATE, riddle_answer)
        speak(wrong_msg)


def save_detected_frames(frame1, frame2, contours, max_area: float) -> Optional[Path]:
    """
    Save a side-by-side comparison screenshot (and individual frames) of the two frames
    (frame1 and frame2) that were compared and exceeded MOTION_THRESHOLD.
    """
    if not SAVE_DETECTED_FRAMES or cv2 is None or np is None or frame1 is None or frame2 is None:
        return None
    try:
        DETECTED_FRAMES_DIR.mkdir(parents=True, exist_ok=True)
        f1_vis = frame1.copy()
        f2_vis = frame2.copy()

        for contour in contours:
            area = cv2.contourArea(contour)
            if area >= MOTION_THRESHOLD:
                x, y, w, h = cv2.boundingRect(contour)
                cv2.rectangle(f1_vis, (x, y), (x + w, y + h), (0, 165, 255), 2)
                cv2.rectangle(f2_vis, (x, y), (x + w, y + h), (0, 255, 0), 2)

        variance = max_area - MOTION_THRESHOLD
        ts_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        file_ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]

        cv2.putText(f1_vis, f"Frame 1 (Before) | {ts_str}", (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(f1_vis, f"Frame 1 (Before) | {ts_str}", (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 165, 255), 1, cv2.LINE_AA)

        label2 = f"Frame 2 (Trigger) | Peak: {int(max_area)}px | Thresh: {MOTION_THRESHOLD}px | Var: +{int(variance)}px"
        cv2.putText(f2_vis, label2, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(f2_vis, label2, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 1, cv2.LINE_AA)

        comparison = np.hstack((f1_vis, f2_vis))
        pair_path = DETECTED_FRAMES_DIR / f"motion_{file_ts}_{int(max_area)}px_pair.jpg"
        f1_path = DETECTED_FRAMES_DIR / f"motion_{file_ts}_{int(max_area)}px_frame1.jpg"
        f2_path = DETECTED_FRAMES_DIR / f"motion_{file_ts}_{int(max_area)}px_frame2.jpg"
        latest_path = DETECTED_FRAMES_DIR / "latest_motion_pair.jpg"

        cv2.imwrite(str(pair_path), comparison)
        cv2.imwrite(str(f1_path), frame1)
        cv2.imwrite(str(f2_path), frame2)
        cv2.imwrite(str(latest_path), comparison)
        print(f"📸 Saved motion comparison frames: {pair_path} (and raw frame1/frame2)")
        return pair_path
    except Exception as e:
        print(f"Notice: Could not save detected frames screenshot: {e}")
        return None


def open_camera(target) -> cv2.VideoCapture:
    """
    Open an OpenCV VideoCapture stream with string and numeric index fallback.

    Attempts to open the specified target (either a path like `/dev/video2` or an
    integer index). If opening the device by string fails, extracts digits from the
    path and attempts opening by integer index.

    Args:
        target (Union[str, int]): Camera device path or index.

    Returns:
        cv2.VideoCapture: Initialized OpenCV VideoCapture object.

    Example:
        >>> cap = open_camera("/dev/video2")
        >>> is_open = cap.isOpened()
    """
    if isinstance(target, str) and target.isdigit():
        target = int(target)
    
    cap = cv2.VideoCapture(target)
    if not cap.isOpened() and isinstance(target, str) and "video" in target:
        # Fallback to numeric index if device string path didn't open
        digits = ''.join(filter(str.isdigit, target))
        if digits:
            idx = int(digits)
            print(f"Device path '{target}' not opened directly; trying index {idx}...")
            cap = cv2.VideoCapture(idx)
    return cap


def main() -> None:
    """
    Core lifecycle loop for the Halloween Doorcam sentinel.

    Initializes models, pre-warms audio, opens the camera, and continuously captures
    video frames to monitor for doorstep motion. When movement exceeds `MOTION_THRESHOLD`,
    triggers `interact()`, pauses for `MOTION_COOLDOWN` seconds, flushes buffered frames,
    and resumes watching.

    Returns:
        None

    Example:
        $ python3 doorcam.py
    """
    init_ml_models()
    warm_audio_cache()
    print(f"Opening camera: {CAMERA_DEVICE}...")
    cap = open_camera(CAMERA_DEVICE)
    
    if not cap.isOpened():
        print(f"ERROR: Could not open camera device '{CAMERA_DEVICE}'. Check device permissions and connections.")
        return

    ret, frame1 = cap.read()
    ret, frame2 = cap.read()
    
    if frame1 is None or frame2 is None:
        print(f"ERROR: Could not read frames from camera '{CAMERA_DEVICE}'.")
        cap.release()
        return
    
    print(f"Watching the door (Headless Mode, threshold: {MOTION_THRESHOLD})... Press Ctrl+C to stop.")
    last_variance_log = time.time()

    try:
        while cap.isOpened():
            # Calculate absolute pixel difference between consecutive video frames
            diff = cv2.absdiff(frame1, frame2)
            gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
            blur = cv2.GaussianBlur(gray, (5, 5), 0)
            _, thresh = cv2.threshold(blur, 20, 255, cv2.THRESH_BINARY)
            dilated = cv2.dilate(thresh, None, iterations=3)
            contours, _ = cv2.findContours(dilated, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

            max_contour_area = 0.0
            motion_detected = False
            for contour in contours:
                area = cv2.contourArea(contour)
                if area > max_contour_area:
                    max_contour_area = area
                if area >= MOTION_THRESHOLD:
                    motion_detected = True

            variance = max_contour_area - MOTION_THRESHOLD
            now = time.time()
            if MOTION_LOG_INTERVAL > 0 and max_contour_area > 0 and (now - last_variance_log) >= MOTION_LOG_INTERVAL and not motion_detected:
                pct = (max_contour_area / MOTION_THRESHOLD) * 100.0 if MOTION_THRESHOLD > 0 else 0.0
                print(
                    f"[Motion Variance] Peak Area: {int(max_contour_area)} px | "
                    f"Threshold: {MOTION_THRESHOLD} px | "
                    f"Variance: {int(variance):+d} px ({pct:.1f}%)"
                )
                last_variance_log = now

            if motion_detected:
                pct = (max_contour_area / MOTION_THRESHOLD) * 100.0 if MOTION_THRESHOLD > 0 else 0.0
                print(
                    f"\n[MOTION DETECTED] Peak Area: {int(max_contour_area)} px | "
                    f"Threshold: {MOTION_THRESHOLD} px | "
                    f"Variance: +{int(variance)} px ({pct:.1f}% of threshold)"
                )
                save_detected_frames(frame1, frame2, contours, max_contour_area)
                interact()

                print(f"Cooldown for {MOTION_COOLDOWN} seconds...")
                # Actively drain buffered frames during cooldown so camera buffer does not retain stale motion
                start_cooldown = time.time()
                while time.time() - start_cooldown < MOTION_COOLDOWN:
                    cap.grab()
                    time.sleep(0.05)

                # Flush any remaining frames and capture two fresh consecutive baseline frames
                for _ in range(5):
                    cap.grab()

                ret, frame1 = cap.read()
                time.sleep(0.1)
                ret, frame2 = cap.read()

                if not ret or frame1 is None or frame2 is None:
                    print(f"ERROR: Lost camera feed from '{CAMERA_DEVICE}'.")
                    break

                print(f"✓ Cooldown complete ({MOTION_COOLDOWN}s). Watching for motion (threshold: {MOTION_THRESHOLD})...\n")
                continue

            frame1 = frame2
            ret, frame2 = cap.read()
            if not ret or frame2 is None:
                print(f"ERROR: Lost camera feed from '{CAMERA_DEVICE}'.")
                break
            time.sleep(0.1) # Throttle loop to maintain low CPU utilization

    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        cap.release()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="🎃 Halloween Doorcam")
    parser.add_argument("--clear-cache", action="store_true", help="Clear all cached audio files and exit")
    parser.add_argument("--warm-cache", action="store_true", help="Pre-generate static dialogue audio files and exit")
    args = parser.parse_args()

    if args.clear_cache:
        clear_audio_cache()
        sys.exit(0)

    if args.warm_cache:
        warm_audio_cache()
        sys.exit(0)

    main()
