#!/usr/bin/env python3
"""
💀 Halloween Skeleton Sentinel - Interactive AI Trick-or-Treat Service
======================================================================
Autonomous Halloween doorstep skeleton that watches for approaching trick-or-treaters
via webcam motion detection, awakens with rattling atmospheric sound effects, greets the
child, asks if they have a trick or treat, listens to their response (and tries to solve
their riddle or respond in character using a local Ollama LLM), and invites them to take
a treat from the bowl!
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
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, List
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
    Context manager to suppress low-level C library stderr output (ALSA/PortAudio/JACK).
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

# --- Edge-TTS Voice & Pitch Settings (Skeleton persona defaults to higher/rattly or configurable) ---
TTS_VOICE = os.getenv("SKELETON_TTS_VOICE", os.getenv("TTS_VOICE", "en-GB-RyanNeural"))
TTS_RATE = os.getenv("SKELETON_TTS_RATE", os.getenv("TTS_RATE", "-5%"))
TTS_PITCH = os.getenv("SKELETON_TTS_PITCH", os.getenv("TTS_PITCH", "-20Hz"))

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

# --- Script Paths & Skeleton Greetings Configuration ---
SCRIPT_DIR = Path(__file__).resolve().parent
SKELETON_GREETINGS_FILE = Path(os.getenv("SKELETON_GREETINGS_FILE", SCRIPT_DIR / "skeleton_greetings.txt"))

DEFAULT_SKELETON_GREETINGS: List[str] = [
    "Clickity-clack! Welcome to my boneyard, little mortal! Do you have a trick or a treat for this old skeleton? Tell me a riddle if you dare!",
    "Rattle, rattle! Happy Halloween! My old bones are itching for a laugh! Do you have a trick, a treat, or a spooky riddle for me?",
    "Clack, clack, clack! Greetings from the crypt, young trick-or-treater! Have you brought a trick or a treat? Give this skeleton your best riddle!",
    "Well shiver my timbers and rattle my ribs! Happy Halloween! Do you have a trick or a treat? Ask me a riddle and see if my hollow skull can guess it!",
    "Brrr, it is chilly when you have no skin! Welcome, little monster! Do you have a trick or a treat for me today?",
    "Ah, a visitor at my doorstep! Careful, do not trip over my funny bone! Do you have a trick or a treat? Hit me with your best Halloween riddle!",
    "Spooky greetings, creature of the night! I am all bones and brains tonight! Do you have a trick or treat, or a riddle to test my skull?",
    "Click-clack! Who rattles at my door? Happy Halloween! Tell me, do you have a trick or a treat?"
]

SKELETON_TREAT_MESSAGE = os.getenv(
    "SKELETON_TREAT_MESSAGE",
    "You may take a treat from the bowl! Happy Halloween!"
)

SKELETON_SILENT_MESSAGE = os.getenv(
    "SKELETON_SILENT_MESSAGE",
    "Cat got your tongue? Or maybe a ghost! That is okay, my rattled friend, you can still take a treat from the bowl! Happy Halloween!"
)

SKELETON_FALLBACK_ANSWERS: List[str] = [
    "Rattle my ribs, that is a good one! My hollow skull is spinning! Go ahead, you can take a treat from the bowl!",
    "Clickity-clack! You stumped this old pile of bones! That was tickling my funny bone! Go on, take a treat from the bowl!",
    "Haha! By my collarbone, that is a spooky one! You have earned your reward—you can take a treat from the bowl!"
]

# --- Audio Cache & Hardware Routing ---
AUDIO_OUTPUT_DEVICE = os.getenv("AUDIO_OUTPUT_DEVICE")
AUDIO_INPUT_DEVICE = os.getenv("AUDIO_INPUT_DEVICE")
PULSE_SERVER = os.getenv("PULSE_SERVER")
MIC_DEVICE_INDEX = os.getenv("MIC_DEVICE_INDEX")
AUDIO_CACHE_DIR = Path(os.getenv("AUDIO_CACHE_DIR", "audio_cache"))
AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# --- Spooky Sound Effects Configuration ---
ENABLE_SOUND_EFFECTS = os.getenv("ENABLE_SOUND_EFFECTS", "true").lower() in ("true", "1", "yes")
FX_MOTION_DETECTED = os.getenv("FX_SKELETON_MOTION", os.getenv("FX_MOTION_DETECTED", "chains"))
FX_CORRECT_ANSWER = os.getenv("FX_CORRECT_ANSWER", "correct_answer")
FX_SILENT_ANSWER = os.getenv("FX_SILENT_ANSWER", "silence_ghost")


def load_skeleton_greetings(file_path: Optional[Path] = None) -> List[str]:
    """
    Load skeleton greetings from skeleton_greetings.txt, falling back to DEFAULT_SKELETON_GREETINGS.
    """
    path = file_path or SKELETON_GREETINGS_FILE
    greetings: List[str] = []
    if path.exists() and path.stat().st_size > 0:
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith(("#", "//")):
                        greetings.append(line)
        except Exception as e:
            print(f"Warning: Could not read skeleton greetings from {path}: {e}")

    if not greetings:
        greetings = list(DEFAULT_SKELETON_GREETINGS)
    return greetings


_greetings_deck: List[str] = []
_last_greetings_mtime: float = 0.0


def get_next_greeting() -> str:
    """
    Retrieve the next skeleton greeting using a non-repeating shuffle deck.
    """
    global _greetings_deck, _last_greetings_mtime
    file_mtime = SKELETON_GREETINGS_FILE.stat().st_mtime if SKELETON_GREETINGS_FILE.exists() else 0.0

    if not _greetings_deck or file_mtime > _last_greetings_mtime:
        loaded = load_skeleton_greetings()
        _greetings_deck = list(loaded)
        random.shuffle(_greetings_deck)
        _last_greetings_mtime = file_mtime

    return _greetings_deck.pop()


def find_microphone_index(target_name: str) -> Tuple[Optional[int], str]:
    """
    Locate the PyAudio device index matching the configured microphone name or keywords.
    """
    if not target_name or target_name.lower() in ("default", "none", ""):
        return None, "Default System Microphone"
    try:
        with suppress_c_stderr():
            mic_names = sr.Microphone.list_microphone_names() if sr else []
        if not mic_names:
            return None, target_name

        clean_target = re.sub(
            r"(?i)\b(analog|digital|stereo|mono|multichannel|capture|source|sink|input|output)\b",
            "",
            target_name
        )
        target_words = [w.lower() for w in re.findall(r"\w+", clean_target) if len(w) > 2]

        for idx, name in enumerate(mic_names):
            if target_name.lower() in name.lower() or name.lower() in target_name.lower():
                return idx, name

        if target_words:
            for idx, name in enumerate(mic_names):
                nl = name.lower()
                if all(w in nl for w in target_words):
                    return idx, name

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
        if peak > (max_val * 0.02) and (peak / max_val) < 0.70:
            scale = min((target_peak * max_val) / peak, 4.0)
            data = np.clip(data * scale, -max_val, max_val).astype(dtype)
            with wave.open(wav_path, "wb") as wf:
                wf.setparams(params)
                wf.writeframes(data.tobytes())
    except Exception as e:
        print(f"Audio normalization notice: {e}")


# Global ML model and hardware singletons
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
            print(f"Notice: Could not connect to Ollama at {hosts_to_try}. Fallback skeleton responses will be used.")

    if whisper_model is None and whisper:
        print(f"Loading Whisper model '{WHISPER_MODEL_NAME}'...")
        whisper_model = whisper.load_model(WHISPER_MODEL_NAME)
        recognizer = sr.Recognizer()

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
    except Exception:
        if temp_file.exists():
            temp_file.unlink(missing_ok=True)
        return phrase, False


def warm_audio_cache() -> None:
    """
    Pre-synthesize all static skeleton greetings and fallback dialogue lines.
    """
    phrases = [
        SKELETON_TREAT_MESSAGE,
        SKELETON_SILENT_MESSAGE,
    ]
    for g in load_skeleton_greetings():
        if g not in phrases:
            phrases.append(g)
    for fb in SKELETON_FALLBACK_ANSWERS:
        if fb not in phrases:
            phrases.append(fb)

    total = len(phrases)
    print(f"Pre-warming skeleton audio cache ({total} dialogue phrases)...")

    cached_count = 0
    hit_count = 0

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
    """
    if not text or not text.strip():
        return

    AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    audio_file = get_cached_audio_path(text)

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


def clean_llm_speech(text: str) -> str:
    """
    Clean markdown symbols, stage directions, or emojis from Ollama output so Edge-TTS reads it naturally.
    """
    # Remove text inside asterisks like *rattles bones*
    text = re.sub(r'\*[^*]+\*', '', text)
    text = text.replace('**', '').replace('__', '').replace('*', '').replace('_', '')
    # Strip emojis / non-ASCII symbols except basic punctuation
    text = re.sub(r'[^\x00-\x7F]+', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def answer_child_with_ollama(kid_input: str) -> str:
    """
    Use the local Ollama LLM to pretend to be a funny, spooky Halloween skeleton,
    attempt to answer the child's riddle (or react to their trick/treat response),
    and tell them they can take a treat from the bowl.
    """
    if ollama_client:
        prompt = (
            "You are a friendly, funny, and spooky Halloween skeleton guarding a candy bowl on a porch. "
            "You just greeted a trick-or-treater and asked if they have a trick or a treat, or a riddle for you.\n"
            f"The child said: \"{kid_input}\"\n\n"
            "Instructions:\n"
            "1. Stay completely in character as a rattling Halloween skeleton (use a quick bone pun or skeletal humor).\n"
            "2. If the child asked a riddle or joke, enthusiastically try to guess or answer the riddle!\n"
            "3. If the child just said 'trick or treat', 'treat', 'trick', or something else, play along with skeletal humor.\n"
            "4. End by explicitly telling the child that they can take a treat from the bowl.\n"
            "5. Keep your entire response very short (2 to 3 sentences maximum), plain spoken text only, no stage directions in asterisks, and no emojis."
        )
        try:
            response = ollama_client.generate(
                model=MODEL,
                prompt=prompt,
                options={"temperature": 0.7, "num_predict": 90}
            )
            raw_reply = response.get("response", "").strip()
            cleaned = clean_llm_speech(raw_reply)
            if cleaned:
                # Ensure it mentions taking a treat from the bowl if the LLM forgot
                if "treat" not in cleaned.lower() and "bowl" not in cleaned.lower():
                    cleaned = f"{cleaned} {SKELETON_TREAT_MESSAGE}"
                return cleaned
        except Exception as e:
            print(f"Notice: Ollama generation error: {e}")

    return random.choice(SKELETON_FALLBACK_ANSWERS)


def interact() -> None:
    """
    Execute the interactive skeleton trick-or-treat flow when motion is triggered:
      1. Play skeleton awakening sound effect (rattling chains/bones).
      2. Greet the child & ask if they have a trick or treat (or riddle).
      3. Listen for the child's response using Whisper STT.
      4. Try to answer the riddle / respond as a Halloween skeleton using local Ollama,
         and tell them they can take a treat from the bowl.
    """
    # 0. Skeleton Awakening Stinger
    if ENABLE_SOUND_EFFECTS and play_sound_effect and FX_MOTION_DETECTED:
        play_sound_effect(FX_MOTION_DETECTED, pulse_server=PULSE_SERVER, audio_output_device=AUDIO_OUTPUT_DEVICE, wait=True)

    # 1. Greet the child & ask if they have a trick or treat
    greeting = get_next_greeting()
    print(f"\n💀 Skeleton Greeting: {greeting}")
    speak(greeting)

    # 2. Listen for the child's response / riddle
    if PRE_LISTEN_DELAY > 0:
        time.sleep(PRE_LISTEN_DELAY)

    print("🎤 Listening for child's trick, treat, or riddle...")
    kid_response = ""

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
            recognizer.phrase_threshold = 0.2
            recognizer.non_speaking_duration = 0.6

            print(f"Ready (energy threshold: {int(recognizer.energy_threshold)}). Speak now!")
            try:
                audio = recognizer.listen(source, timeout=LISTEN_TIMEOUT, phrase_time_limit=LISTEN_PHRASE_TIME_LIMIT)
                with open("temp_skeleton_mic.wav", "wb") as f:
                    f.write(audio.get_wav_data())

                normalize_audio("temp_skeleton_mic.wav")

                transcribe_out = whisper_model.transcribe(
                    "temp_skeleton_mic.wav",
                    language="en",
                    fp16=False,
                    temperature=0.0,
                    condition_on_previous_text=False,
                    no_speech_threshold=0.6,
                    compression_ratio_threshold=2.2
                )
                raw_text = transcribe_out.get("text", "").strip()

                is_hallucination = False
                segments = transcribe_out.get("segments", [])
                if segments:
                    avg_no_speech = sum(s.get("no_speech_prob", 0) for s in segments) / len(segments)
                    if avg_no_speech > 0.65:
                        is_hallucination = True

                words = raw_text.lower().split()
                if len(words) > 8:
                    unique_ratio = len(set(words)) / len(words)
                    if unique_ratio < 0.40:
                        is_hallucination = True

                if is_hallucination or not raw_text:
                    kid_response = ""
                    print("No distinct speech detected (filtered silence/background noise).")
                else:
                    kid_response = raw_text
                    print(f"Child said: {kid_response}")
            except sr.WaitTimeoutError:
                print("No audio detected.")
            except Exception as e:
                print(f"Microphone error: {e}")

    # 3. Answer the riddle / respond via Ollama and say they can take a treat from the bowl
    if not kid_response:
        print("Child did not speak in time. Inviting them to take a treat anyway.")
        if ENABLE_SOUND_EFFECTS and play_sound_effect and FX_SILENT_ANSWER:
            play_sound_effect(FX_SILENT_ANSWER, pulse_server=PULSE_SERVER, audio_output_device=AUDIO_OUTPUT_DEVICE, wait=True)
        speak(SKELETON_SILENT_MESSAGE)
        return

    print(f"Thinking of skeleton answer via Ollama for: '{kid_response}'...")
    skeleton_reply = answer_child_with_ollama(kid_response)
    print(f"💀 Skeleton Reply: {skeleton_reply}")

    if ENABLE_SOUND_EFFECTS and play_sound_effect and FX_CORRECT_ANSWER:
        play_sound_effect(FX_CORRECT_ANSWER, pulse_server=PULSE_SERVER, audio_output_device=AUDIO_OUTPUT_DEVICE, wait=True)
    speak(skeleton_reply)


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
    """
    if isinstance(target, str) and target.isdigit():
        target = int(target)

    cap = cv2.VideoCapture(target)
    if not cap.isOpened() and isinstance(target, str) and "video" in target:
        digits = ''.join(filter(str.isdigit, target))
        if digits:
            idx = int(digits)
            print(f"Device path '{target}' not opened directly; trying index {idx}...")
            cap = cv2.VideoCapture(idx)
    return cap


def main() -> None:
    """
    Core lifecycle loop for the Halloween Skeleton service.
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

    print(f"💀 Skeleton Sentinel watching the door (Headless Mode, threshold: {MOTION_THRESHOLD})... Press Ctrl+C to stop.")
    last_variance_log = time.time()

    try:
        while cap.isOpened():
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
                start_cooldown = time.time()
                while time.time() - start_cooldown < MOTION_COOLDOWN:
                    cap.grab()
                    time.sleep(0.05)

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
            time.sleep(0.1)

    except KeyboardInterrupt:
        print("\nShutting down Skeleton Sentinel...")
    finally:
        cap.release()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="💀 Halloween Skeleton Sentinel")
    parser.add_argument("--clear-cache", action="store_true", help="Clear all cached audio files and exit")
    parser.add_argument("--warm-cache", action="store_true", help="Pre-generate static dialogue audio files and exit")
    parser.add_argument("--test-interact", action="store_true", help="Run a single interactive turn without camera motion")
    args = parser.parse_args()

    if args.clear_cache:
        clear_audio_cache()
        sys.exit(0)

    if args.warm_cache:
        warm_audio_cache()
        sys.exit(0)

    if args.test_interact:
        init_ml_models()
        interact()
        sys.exit(0)

    main()

