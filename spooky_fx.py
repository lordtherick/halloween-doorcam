#!/usr/bin/env python3
"""
🎃 Halloween Doorcam - Spooky Sound Effects & AudioCraft Module
==============================================================
Manages, synthesizes, and pre-generates Halloween atmospheric audio,
sound effects, and stingers using Meta's AudioCraft (AudioGen) or the
built-in high-fidelity procedural sound engine.

Architecture:
-------------
1. Dual-Engine Generation:
   - Procedural Synthesis (Default): High-speed, studio-quality acoustic
     modeling using NumPy. Models physical acoustics of church bells (Rayleigh
     inharmonic partials & beating), stone friction, stick-slip wood creaks,
     celesta chime cascades with fairy-dust twinkles, hollow bronze dungeon gongs,
     guttural monster vocal tract formants with subharmonic gravel, and
     atmospheric convolution reverb. Generates cinematic stingers in <50ms.
   - AudioCraft AudioGen (Optional): Meta's generative audio diffusion model
     for novel text-prompt-based sound effects when installed.
2. Caching Pipeline:
   - Generates 16-bit PCM WAV -> transcodes to MP3 via ffmpeg for fast streaming.
   - Files are stored in `audio_cache/fx/` and indexed by profile keys.
3. System Audio Router:
   - Discovers available player CLI tools (`pw-play`, `mpg123`, `ffplay`, `paplay`, `aplay`)
   - Transparently handles PulseAudio sockets (Docker) and PipeWire (Host).
"""

import os
import re
import sys
import wave
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

try:
    import numpy as np
except ImportError:
    np = None

# AudioCraft import on demand - gracefully handles systems without torch/audiocraft
AUDIOCRAFT_AVAILABLE = False
try:
    from audiocraft.models import AudioGen
    from audiocraft.data.audio import audio_write
    AUDIOCRAFT_AVAILABLE = True
except ImportError:
    AudioGen = None
    audio_write = None


# Directory paths: Ensure audio_cache/fx exists for storing pre-warmed effects
SCRIPT_DIR = Path(__file__).resolve().parent
FX_DIR = SCRIPT_DIR / "audio_cache" / "fx"
FX_DIR.mkdir(parents=True, exist_ok=True)

# Pre-defined Halloween Doorcam Sound Profiles
# Each profile defines a descriptive title, AudioCraft text prompt, duration, and intent
DEFAULT_FX_PROFILES = {
    "motion_detected": {
        "title": "Gargoyle Awakening (Crypt Gate Grinding)",
        "prompt": "heavy ancient stone gate grinding open, crypt door dragging on cobblestone, deep rumble with spooky wind",
        "duration": 3.2,
        "description": "Played immediately when camera motion is detected as the gargoyle awakens."
    },
    "riddle_intro": {
        "title": "Riddle Chime (Gothic Bell & Chuckle)",
        "prompt": "deep ominous gothic cathedral church bell tolling with sinister echoing dark laugh",
        "duration": 3.2,
        "description": "Played right before the gargoyle presents the riddle to the child."
    },
    "correct_answer": {
        "title": "Treasure Revealed (Magical Spooky Chime)",
        "prompt": "magical mystical Halloween chime with enchanted sparkles, happy spooky fanfare, sweet treat celebration",
        "duration": 2.8,
        "description": "Played when the child solves the riddle correctly before granting candy."
    },
    "wrong_answer": {
        "title": "Dungeon Gong (Discordant Failure & Mocking Echo)",
        "prompt": "deep hollow bronze dungeon gong ringing with eerie discordant resonance, mocking ghost chuckle",
        "duration": 3.0,
        "description": "Played when the child answers incorrectly."
    },
    "silence_ghost": {
        "title": "Haunted Graveyard Wind (Ghostly Whistle)",
        "prompt": "cold eerie howling wind blowing through dead trees in an empty cemetery, ghostly whispers fading",
        "duration": 3.2,
        "description": "Played when no child speech is detected."
    },
    "chains": {
        "title": "Dungeon Chains (Rattling Iron Shackles)",
        "prompt": "heavy rusty iron chains dragging and rattling across wet stone dungeon floor, eerie echoing clatter",
        "duration": 3.0,
        "description": "Atmospheric stinger of heavy rattling dungeon chains."
    },
    "creaky_door": {
        "title": "Haunted Crypt Door (Creaking Wooden Hinges)",
        "prompt": "slow agonizingly loud wooden door hinge creaking open in a quiet haunted mansion",
        "duration": 3.2,
        "description": "Slow, eerie wooden door creak for atmospheric tension."
    },
    "thunder": {
        "title": "Distant Thunder (Rolling Storm Rumble)",
        "prompt": "distant menacing rolling thunderclap echoing over a dark stormy night sky",
        "duration": 3.5,
        "description": "Deep atmospheric low rumble of rolling midnight thunder."
    },
    "evil_laugh": {
        "title": "Gargoyle Chuckle (Deep Sinister Laugh)",
        "prompt": "deep raspy sinister gargoyle chuckle echoing in an ancient stone courtyard",
        "duration": 2.8,
        "description": "Deep playful menacing gargoyle laughter."
    },
    "witch_cackle": {
        "title": "Wicked Witch (Maniacal High Cackle)",
        "prompt": "maniacal wicked witch laughing and cackling around a boiling cauldron",
        "duration": 3.0,
        "description": "High-pitched cackling wicked witch laughter."
    },
    "monster_roar": {
        "title": "Gargoyle Roar (Terrifying Creature Snarl)",
        "prompt": "deep visceral monster roar and snarling beast echo",
        "duration": 3.2,
        "description": "Intense menacing creature roar."
    },
    "jumpscare": {
        "title": "Jump Scare (Bloodcurdling Screech & Horror Strike)",
        "prompt": "sudden terrifying jump scare stinger with screech and thunderous impact",
        "duration": 2.5,
        "description": "Sudden shock stinger for maximum fright."
    }
}


def get_fx_path(name: str, format_ext: str = "mp3") -> Path:
    """
    Compute the canonical filesystem destination path for a sound effect.

    Sanitizes the effect name into a filesystem-safe identifier and appends
    the requested extension within the `audio_cache/fx/` directory.

    Args:
        name (str): Identifier key of the sound effect (e.g. 'motion_detected').
        format_ext (str): File extension without leading dot ('mp3' or 'wav'). Defaults to 'mp3'.

    Returns:
        Path: Absolute pathlib.Path object pointing to the expected cache file.
    """
    clean_name = re.sub(r"[^\w\-]", "_", name.lower())
    return FX_DIR / f"{clean_name}.{format_ext}"


def is_fx_cached(name: str) -> bool:
    """
    Check if a valid, pre-rendered sound effect file is present in the cache.

    Validates that either an MP3 or WAV version exists and contains non-trivial
    audio data (> 1024 bytes) to guard against truncated or zero-byte files.

    Args:
        name (str): Identifier key of the sound effect to check.

    Returns:
        bool: True if an MP3 or WAV file exists and exceeds 1 KB; False otherwise.
    """
    mp3_path = get_fx_path(name, "mp3")
    wav_path = get_fx_path(name, "wav")
    return (mp3_path.exists() and mp3_path.stat().st_size > 1024) or (wav_path.exists() and wav_path.stat().st_size > 1024)


def convert_wav_to_mp3(wav_path: Path, mp3_path: Path) -> bool:
    """
    Transcode an uncompressed WAV file into an optimized MP3 file using ffmpeg.

    Applies the LAME MP3 codec with high variable-bitrate quality (-qscale:a 2).

    Args:
        wav_path (Path): Path to the existing input WAV file.
        mp3_path (Path): Destination Path where the MP3 file will be written.

    Returns:
        bool: True if ffmpeg exited with returncode 0 and the output file exists;
              False if ffmpeg failed or is not installed.
    """
    try:
        res = subprocess.run([
            "ffmpeg", "-y", "-i", str(wav_path),
            "-codec:a", "libmp3lame", "-qscale:a", "2",
            str(mp3_path)
        ], capture_output=True, text=True, timeout=10)
        return res.returncode == 0 and mp3_path.exists()
    except Exception as e:
        print(f"ffmpeg conversion notice: {e}")
        return False


# ==============================================================================
# Procedural Audio DSP Helpers
# ==============================================================================

def _get_brown_noise(n: int, sr: int = 44100) -> "np.ndarray":
    """Generate true brown/red (1/f^2) noise with zero DC offset."""
    white = np.random.normal(0, 1, n)
    fft_w = np.fft.rfft(white)
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    freqs[0] = 1.0
    scale = 1.0 / freqs
    scale[0] = 0.0
    brown = np.fft.irfft(fft_w * scale, n=n)
    std = np.std(brown)
    return brown / (std if std > 1e-6 else 1.0)


def _get_pink_noise(n: int, sr: int = 44100) -> "np.ndarray":
    """Generate true pink (1/f) noise with zero DC offset."""
    white = np.random.normal(0, 1, n)
    fft_w = np.fft.rfft(white)
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    freqs[0] = 1.0
    scale = 1.0 / np.sqrt(freqs)
    scale[0] = 0.0
    pink = np.fft.irfft(fft_w * scale, n=n)
    std = np.std(pink)
    return pink / (std if std > 1e-6 else 1.0)


def _apply_fft_filter(signal: "np.ndarray", sr: int = 44100, low_pass: float = None,
                      high_pass: float = None, peaks: list = None,
                      roll_off_order: int = 4) -> "np.ndarray":
    """
    Apply zero-phase frequency-domain filtering: lowpass, highpass, and resonant EQ peaks.
    peaks: list of (freq, Q, gain_linear)
    """
    n = len(signal)
    fft_sig = np.fft.rfft(signal)
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    h = np.ones_like(freqs, dtype=np.float64)

    if high_pass is not None and high_pass > 0:
        h *= 1.0 / (1.0 + (high_pass / np.maximum(freqs, 1e-4)) ** roll_off_order)

    if low_pass is not None and low_pass < sr / 2:
        h *= 1.0 / (1.0 + (freqs / low_pass) ** roll_off_order)

    if peaks:
        for f_p, q, gain in peaks:
            bw = f_p / q
            h += gain * np.exp(-0.5 * ((freqs - f_p) / (bw / 2.0 + 1e-6)) ** 2)

    return np.fft.irfft(fft_sig * h, n=n)


def _apply_spatial_reverb(signal: "np.ndarray", sr: int = 44100, rt60: float = 1.6,
                          damp_freq: float = 2200.0, wet: float = 0.35,
                          predelay_ms: float = 20.0) -> "np.ndarray":
    """
    Algorithmic convolution reverb simulating stone crypts, cathedrals,
    and dungeons using power-of-2 fast FFT convolution.
    """
    n = len(signal)
    ir_len = int(sr * rt60)
    t_ir = np.linspace(0, rt60, ir_len, endpoint=False)

    # Exponential diffuse decay envelope
    ir = np.random.normal(0, 1, ir_len) * np.exp(-3.5 * t_ir / rt60)

    # Frequency-dependent air & stone wall damping
    f_ir = np.fft.rfftfreq(ir_len, 1.0 / sr)
    fft_ir = np.fft.rfft(ir)
    fft_ir *= 1.0 / (1.0 + (f_ir / damp_freq) ** 2)
    ir = np.fft.irfft(fft_ir, n=ir_len)

    # Early reflection discrete taps (stone room boundaries)
    taps = [(18, 0.45), (32, 0.35), (48, 0.28), (67, 0.22), (92, 0.18)]
    for d_ms, g in taps:
        idx = int(sr * d_ms / 1000.0)
        if idx < ir_len:
            ir[idx] += g

    # Pre-delay
    p_del = int(sr * predelay_ms / 1000.0)
    if p_del > 0:
        ir = np.pad(ir, (p_del, 0))[:ir_len]

    # Power of 2 fast FFT convolution
    tot_len = 2 ** int(np.ceil(np.log2(n + ir_len - 1)))
    wet_sig = np.fft.irfft(np.fft.rfft(signal, tot_len) * np.fft.rfft(ir, tot_len))[:n]

    wet_norm = np.std(wet_sig)
    if wet_norm > 1e-6:
        wet_sig = (wet_sig / wet_norm) * np.std(signal)

    dry_gain = np.sqrt(1.0 - wet)
    wet_gain = np.sqrt(wet)
    return dry_gain * signal + wet_gain * wet_sig


def _finalize_audio(audio: "np.ndarray", drive: float = 1.1, peak_db: float = -1.0) -> "np.ndarray":
    """Apply musical analog tape saturation and normalize to target peak dB."""
    if drive > 1.0:
        audio = np.tanh(drive * audio) / np.tanh(drive)
    peak = np.max(np.abs(audio))
    target = 10.0 ** (peak_db / 20.0)
    if peak > 1e-6:
        audio = (audio / peak) * target
    return audio


# ==============================================================================
# Individual Acoustic Synthesizers
# ==============================================================================

def _synth_motion_detected(duration: float, sr: int) -> "np.ndarray":
    """Ancient heavy crypt gate grinding open with sub-bass seismic rumble and stone thud."""
    n = int(sr * duration)
    t = np.linspace(0, duration, n, endpoint=False)

    # 1. Seismic low-end rumble (sub-bass brown noise + 38Hz sub drone)
    brown = _get_brown_noise(n, sr)
    rumble = _apply_fft_filter(brown, sr, low_pass=75.0)
    rumble = (rumble / np.std(rumble)) * 0.45
    sub_drone = 0.35 * np.sin(2 * np.pi * 38.0 * t) * (1.0 + 0.2 * np.sin(2 * np.pi * 1.5 * t))
    rumble += sub_drone

    # 2. Granular stone friction & grinding texture
    pink = _get_pink_noise(n, sr)
    stone_peaks = [(180, 4.0, 1.4), (360, 5.0, 1.8), (740, 6.0, 1.2), (1280, 8.0, 0.8)]
    stone_texture = _apply_fft_filter(pink, sr, low_pass=2000.0, high_pass=120.0, peaks=stone_peaks)
    friction_mod = np.clip(
        0.4 + 0.3 * np.sin(2 * np.pi * 9.5 * t) +
        0.2 * np.sin(2 * np.pi * 17.3 * t) +
        0.15 * np.sin(2 * np.pi * 31.0 * t), 0.0, 1.0
    )
    stone_grind = (stone_texture / np.std(stone_texture)) * friction_mod * 0.4

    # 3. Resonant creaking stone scrape sliding open
    scrape_f = 240.0 - 55.0 * (t / duration) + 18.0 * np.sin(2 * np.pi * 3.8 * t)
    phase = 2 * np.pi * np.cumsum(scrape_f) / sr
    scrape = 0.22 * np.sin(phase) * friction_mod

    # 4. Final stone gate lock / settling impact at ~75% of duration
    thud_time = duration * 0.75
    thud_idx = int(thud_time * sr)
    thud_len = min(n - thud_idx, int(0.6 * sr))
    thud_layer = np.zeros(n)
    if thud_len > 0:
        t_thud = np.linspace(0, 0.6, thud_len, endpoint=False)
        thud_tone = np.sin(2 * np.pi * 52.0 * np.exp(-5.0 * t_thud) * t_thud) * np.exp(-10.0 * t_thud)
        thud_crack = np.random.normal(0, 0.5, thud_len) * np.exp(-22.0 * t_thud)
        thud_crack = _apply_fft_filter(thud_crack, sr, low_pass=1200.0)
        thud_layer[thud_idx:thud_idx + thud_len] = (thud_tone * 0.6 + thud_crack * 0.4) * 0.8

    env = np.minimum(t / 0.5, 1.0) * np.exp(-0.7 * np.maximum(0, t - (duration - 1.0)))
    raw = (rumble + stone_grind + scrape) * env + thud_layer

    reverbed = _apply_spatial_reverb(raw, sr, rt60=2.0, damp_freq=1800.0, wet=0.42, predelay_ms=25.0)
    return _finalize_audio(reverbed, drive=1.15)


def _synth_riddle_intro(duration: float, sr: int) -> "np.ndarray":
    """Authentic gothic cathedral church bell with inharmonic Rayleigh partials, beating, and gargoyle chuckle."""
    n = int(sr * duration)
    t = np.linspace(0, duration, n, endpoint=False)

    # 1. Gothic Cathedral Bell Toll (Fundamental C3 ~ 130.81 Hz)
    f0 = 130.81
    bell_partials = [
        (0.50, 0.45, 0.85, 0.4),   # Hum note (sub-octave)
        (1.00, 0.60, 1.10, 0.7),   # Prime (fundamental strike)
        (1.20, 0.50, 1.30, 1.1),   # Tierce (minor 3rd - classic gothic gloom!)
        (1.50, 0.35, 1.60, 1.3),   # Quint (fifth)
        (2.00, 0.40, 2.10, 1.8),   # Nominal (octave)
        (2.50, 0.22, 2.70, 2.2),   # Deciem (tenth)
        (2.76, 0.25, 3.20, 2.6),   # Undeciem
        (3.00, 0.18, 3.80, 3.1),   # Duodeciem
        (4.15, 0.14, 5.00, 4.0),   # Upper inharmonics
        (5.42, 0.10, 6.20, 5.2),
        (6.78, 0.08, 7.50, 6.5),
    ]

    bell = np.zeros(n, dtype=np.float64)
    for ratio, amp, decay, beat_f in bell_partials:
        freq = f0 * ratio
        f_a = freq - beat_f * 0.5
        f_b = freq + beat_f * 0.5
        partial_wave = 0.5 * (np.sin(2 * np.pi * f_a * t) + np.sin(2 * np.pi * f_b * t))
        bell += amp * partial_wave * np.exp(-decay * t)

    # Metallic hammer strike transient (initial clapper hit on bronze)
    hit_len = min(n, int(0.04 * sr))
    t_hit = t[:hit_len]
    hit = np.random.normal(0, 0.8, hit_len) * np.exp(-120.0 * t_hit)
    hit = _apply_fft_filter(hit, sr, low_pass=4500.0, high_pass=800.0)
    bell[:hit_len] += hit * 0.5

    # 2. Sinister Gargoyle Chuckle echoing in the cathedral at t = 1.3s
    chuckle = np.zeros(n, dtype=np.float64)
    chuckle_starts = [1.30, 1.62, 1.90, 2.18]
    pitches = [102.0, 94.0, 86.0, 78.0]

    for p_t, pitch in zip(chuckle_starts, pitches):
        if p_t >= duration:
            continue
        p_len = min(n - int(p_t * sr), int(0.24 * sr))
        p_idx = int(p_t * sr)
        if p_len <= 0:
            continue
        tp = np.linspace(0, 0.24, p_len, endpoint=False)
        pulse_phase = 2 * np.pi * pitch * tp
        glottal = (np.sin(pulse_phase) + 0.4 * np.sin(pulse_phase * 2) + 0.25 * np.sin(pulse_phase * 0.5))
        heh_peaks = [(420, 5.0, 2.5), (1050, 6.0, 2.0), (2200, 7.0, 1.2)]
        pulse_voice = _apply_fft_filter(glottal, sr, low_pass=3200.0, high_pass=150.0, peaks=heh_peaks)
        aspiration = np.random.normal(0, 0.15, p_len) * np.sin(np.pi * (tp / 0.24))
        aspiration = _apply_fft_filter(aspiration, sr, low_pass=2800.0, high_pass=400.0)
        env_pulse = np.sin(np.pi * (tp / 0.24)) ** 1.5
        chuckle[p_idx:p_idx + p_len] += (pulse_voice * 0.7 + aspiration * 0.3) * env_pulse * 0.45

    combined = bell * 0.85 + chuckle * 0.4
    reverbed = _apply_spatial_reverb(combined, sr, rt60=2.5, damp_freq=2800.0, wet=0.40, predelay_ms=30.0)
    return _finalize_audio(reverbed, drive=1.1)


def _synth_correct_answer(duration: float, sr: int) -> "np.ndarray":
    """Treasure Revealed: Enchanted celesta chime arpeggio with cascading fairy dust and warm treat fanfare."""
    n = int(sr * duration)
    t = np.linspace(0, duration, n, endpoint=False)

    # 1. Magical Celesta / Crystal Bells (Enchanted pentatonic/lydian celebration)
    chime_score = [
        (0.00, 587.33, 0.55),   # D5
        (0.10, 739.99, 0.60),   # F#5
        (0.20, 880.00, 0.65),   # A5
        (0.30, 1108.73, 0.70),  # C#6
        (0.40, 1318.51, 0.75),  # E6
        (0.52, 1760.00, 0.90),  # A6 (triumph top note)
        (0.70, 2217.46, 0.65),  # C#7 (shimmer echo)
    ]

    chimes = np.zeros(n, dtype=np.float64)
    for start_t, freq, note_gain in chime_score:
        start_idx = int(start_t * sr)
        rem_len = n - start_idx
        if rem_len <= 0:
            continue
        t_note = t[:rem_len]
        tone = (
            np.sin(2 * np.pi * freq * t_note) +
            0.35 * np.sin(2 * np.pi * (freq * 2.756) * t_note) * np.exp(-4.5 * t_note) +
            0.18 * np.sin(2 * np.pi * (freq * 5.404) * t_note) * np.exp(-7.0 * t_note) +
            0.12 * np.sin(2 * np.pi * (freq * 2.0) * t_note)
        )
        hit_len = min(rem_len, int(0.015 * sr))
        hit = np.random.normal(0, 0.3, hit_len) * np.exp(-150.0 * t_note[:hit_len])
        hit = _apply_fft_filter(hit, sr, low_pass=3000.0, high_pass=1000.0)
        tone[:hit_len] += hit

        env = np.exp(-2.6 * t_note)
        chimes[start_idx:] += tone * env * note_gain * 0.38

    # 2. Sparkling fairy dust (30 randomized micro-twinkles)
    sparkles = np.zeros(n, dtype=np.float64)
    rng = np.random.RandomState(1337)
    sparkle_times = rng.uniform(0.15, min(duration - 0.5, 1.8), 30)
    sparkle_freqs = rng.uniform(2200.0, 4800.0, 30)

    for st, sf in zip(sparkle_times, sparkle_freqs):
        s_idx = int(st * sr)
        s_len = min(n - s_idx, int(0.35 * sr))
        if s_len <= 0:
            continue
        ts = t[:s_len]
        s_tone = np.sin(2 * np.pi * sf * ts) + 0.3 * np.sin(2 * np.pi * (sf * 1.5) * ts)
        s_env = np.exp(-14.0 * ts)
        sparkles[s_idx:s_idx + s_len] += s_tone * s_env * 0.12

    # 3. Warm harmonic swelling pad (rewarding treat chord: D3, A3, D4, F#4)
    pad = (
        0.35 * np.sin(2 * np.pi * 146.83 * t) +
        0.25 * np.sin(2 * np.pi * 220.00 * t) +
        0.20 * np.sin(2 * np.pi * 293.66 * t) +
        0.18 * np.sin(2 * np.pi * 369.99 * t)
    )
    pad_env = np.sin(np.pi * np.clip(t / 2.0, 0.0, 1.0)) ** 1.8 * np.exp(-0.6 * t)
    pad_layer = pad * pad_env * 0.32

    raw = chimes + sparkles + pad_layer
    reverbed = _apply_spatial_reverb(raw, sr, rt60=2.2, damp_freq=4500.0, wet=0.42, predelay_ms=15.0)
    return _finalize_audio(reverbed, drive=1.05)


def _synth_wrong_answer(duration: float, sr: int) -> "np.ndarray":
    """Dungeon Gong: Subterranean bronze gong of doom with pitch droop, tritone clash, and mocking sigh."""
    n = int(sr * duration)
    t = np.linspace(0, duration, n, endpoint=False)

    # 1. Deep Bronze Dungeon Gong (F2 ~ 87.3 Hz)
    f0 = 87.31
    pitch_warp = np.exp(-0.15 * t)
    f_t = f0 * pitch_warp
    phase_base = 2 * np.pi * np.cumsum(f_t) / sr

    gong_modes = [
        (1.00, 0.65, 0.9),   # Fundamental
        (1.08, 0.50, 1.1),   # Minor second clash (dissonant eerie doom beating!)
        (1.41, 0.40, 1.4),   # Tritone clash (the devil's interval)
        (1.73, 0.35, 1.8),
        (2.14, 0.28, 2.2),
        (2.65, 0.22, 2.8),
        (3.16, 0.18, 3.5),
        (4.05, 0.12, 4.5),
    ]

    gong = np.zeros(n, dtype=np.float64)
    for ratio, amp, decay in gong_modes:
        mode_phase = phase_base * ratio
        shimmer = 0.15 * np.sin(2 * np.pi * 4.2 * t)
        gong += amp * np.sin(mode_phase + shimmer) * np.exp(-decay * t)

    # Heavy padded mallet impact
    hit_len = min(n, int(0.08 * sr))
    t_hit = t[:hit_len]
    mallet_boom = np.sin(2 * np.pi * 58.0 * np.exp(-8.0 * t_hit) * t_hit) * np.exp(-18.0 * t_hit)
    mallet_contact = np.random.normal(0, 0.6, hit_len) * np.exp(-35.0 * t_hit)
    mallet_contact = _apply_fft_filter(mallet_contact, sr, low_pass=1500.0)
    gong[:hit_len] += (mallet_boom * 0.7 + mallet_contact * 0.3) * 0.8

    # 2. Ghostly Mocking Sigh / Whispering Breath at 1.1s
    sigh_start = int(1.1 * sr)
    sigh_len = min(n - sigh_start, int(1.2 * sr))
    if sigh_start < n and sigh_len > 0:
        ts = np.linspace(0, 1.2, sigh_len, endpoint=False)
        breath = np.random.normal(0, 0.25, sigh_len)
        breath_filt = _apply_fft_filter(breath, sr, low_pass=900.0, high_pass=280.0, peaks=[(450, 4.0, 1.5)])
        breath_env = np.sin(np.pi * (ts / 1.2)) ** 1.5 * np.exp(-0.8 * ts)
        gong[sigh_start:sigh_start + sigh_len] += breath_filt * breath_env * 0.28

    reverbed = _apply_spatial_reverb(gong, sr, rt60=2.4, damp_freq=2000.0, wet=0.45, predelay_ms=25.0)
    return _finalize_audio(reverbed, drive=1.12)


def _synth_silence_ghost(duration: float, sr: int) -> "np.ndarray":
    """Haunted cemetery wind with organic low-frequency gusts and eerie whistling through barren trees."""
    n = int(sr * duration)
    t = np.linspace(0, duration, n, endpoint=False)

    # 1. Warm organic wind base (Pink & Brown noise)
    brown = _get_brown_noise(n, sr)
    pink = _get_pink_noise(n, sr)

    wind_gust = _apply_fft_filter(brown, sr, low_pass=260.0, high_pass=35.0)
    gust_env = np.sin(np.pi * np.clip(t / (duration * 0.9), 0.0, 1.0)) ** 1.4
    low_wind = (wind_gust / np.std(wind_gust)) * gust_env * 0.45

    # 2. Resonant eerie whistle through barren branches and tombstones
    whistle_f = 520.0 + 140.0 * np.sin(2 * np.pi * 0.35 * t) + 45.0 * np.sin(2 * np.pi * 0.9 * t)
    phase_w = 2 * np.pi * np.cumsum(whistle_f) / sr
    whistle_carrier = 0.22 * np.sin(phase_w)

    whistle_air = _apply_fft_filter(pink, sr, low_pass=1200.0, high_pass=350.0, peaks=[(580, 7.0, 2.5), (920, 8.0, 1.2)])
    whistle_air = (whistle_air / np.std(whistle_air)) * 0.25
    whistle = (whistle_carrier + whistle_air) * gust_env

    # 3. Ghostly whispery harmonic drift
    ghost_drone = 0.15 * np.sin(2 * np.pi * 329.63 * t) * np.exp(-0.35 * t)
    ghost_drone += 0.12 * np.sin(2 * np.pi * 392.00 * t) * np.exp(-0.45 * t)

    combined = low_wind + whistle * 0.6 + ghost_drone * 0.3
    reverbed = _apply_spatial_reverb(combined, sr, rt60=2.6, damp_freq=2400.0, wet=0.48, predelay_ms=35.0)
    return _finalize_audio(reverbed, drive=1.05)


def _synth_chains(duration: float, sr: int) -> "np.ndarray":
    """Dungeon Chains: Heavy rattling forged iron links clattering and dragging across stone dungeon floor."""
    n = int(sr * duration)
    t = np.linspace(0, duration, n, endpoint=False)

    rng = np.random.RandomState(42)
    clink_offsets = [
        0.10, 0.22, 0.31, 0.42, 0.50, 0.57, 0.63, 0.70,
        0.82, 0.98, 1.15, 1.30, 1.52, 1.80, 2.10, 2.35
    ]

    chains = np.zeros(n, dtype=np.float64)
    for ct in clink_offsets:
        if ct >= duration:
            continue
        c_idx = int(ct * sr)
        c_len = min(n - c_idx, int(0.4 * sr))
        if c_len <= 0:
            continue
        tc = t[:c_len]
        f_base = rng.uniform(1100.0, 1800.0)
        mode1 = f_base
        mode2 = f_base * 2.34
        mode3 = f_base * 3.78
        mode4 = f_base * 5.12

        ring = (
            0.50 * np.sin(2 * np.pi * mode1 * tc) * np.exp(-18.0 * tc) +
            0.35 * np.sin(2 * np.pi * mode2 * tc) * np.exp(-28.0 * tc) +
            0.25 * np.sin(2 * np.pi * mode3 * tc) * np.exp(-42.0 * tc) +
            0.15 * np.sin(2 * np.pi * mode4 * tc) * np.exp(-60.0 * tc)
        )
        hit_len = min(c_len, int(0.01 * sr))
        hit = np.random.normal(0, 0.4, hit_len)
        ring[:hit_len] += hit * 0.4

        clink_gain = rng.uniform(0.6, 1.0)
        chains[c_idx:c_idx + c_len] += ring * clink_gain * 0.45

    # Heavy iron drag friction against wet stone
    drag_noise = _get_pink_noise(n, sr)
    drag_filt = _apply_fft_filter(drag_noise, sr, low_pass=2800.0, high_pass=250.0, peaks=[(750, 4.0, 1.2), (1600, 5.0, 0.8)])
    drag_env = np.clip(0.6 * np.sin(np.pi * np.clip(t / 2.0, 0.0, 1.0)) * (1.0 + 0.3 * np.sin(2 * np.pi * 6.5 * t)), 0.0, 1.0)
    drag = (drag_filt / np.std(drag_filt)) * drag_env * 0.22

    combined = chains + drag
    reverbed = _apply_spatial_reverb(combined, sr, rt60=2.2, damp_freq=3200.0, wet=0.38, predelay_ms=20.0)
    return _finalize_audio(reverbed, drive=1.1)


def _synth_creaky_door(duration: float, sr: int) -> "np.ndarray":
    """Haunted Crypt Door: Stick-slip physical friction model of agonizingly slow rusty wooden door creak."""
    n = int(sr * duration)
    t = np.linspace(0, duration, n, endpoint=False)

    wood_peaks = [(280, 5.0, 2.0), (520, 6.0, 2.5), (880, 7.0, 1.8), (1420, 8.0, 1.2)]
    f_slip = 28.0 + 190.0 * np.sin(np.pi * np.clip(t / (duration * 0.9), 0.0, 1.0)) ** 2.2
    rng = np.random.RandomState(99)
    jitter = 15.0 * np.sin(2 * np.pi * 7.5 * t) + 8.0 * (rng.rand(n) - 0.5)
    f_slip = np.maximum(15.0, f_slip + jitter)

    phase_slip = 2 * np.pi * np.cumsum(f_slip) / sr
    slip_wave = np.mod(phase_slip, 2 * np.pi) / (2 * np.pi) - 0.5

    creak_body = _apply_fft_filter(slip_wave, sr, low_pass=2400.0, high_pass=150.0, peaks=wood_peaks)
    creak_body = (creak_body / np.std(creak_body)) * 0.45

    wood_groan = 0.25 * np.sin(2 * np.pi * 95.0 * t) * (1.0 + 0.3 * np.sin(2 * np.pi * 4.0 * t))
    groan_env = np.sin(np.pi * np.clip(t / (duration * 0.9), 0.0, 1.0)) ** 1.5

    # Final settle thud
    thud_idx = int((duration - 0.5) * sr)
    thud_len = min(n - thud_idx, int(0.4 * sr))
    thud = np.zeros(n)
    if thud_idx < n and thud_len > 0:
        tt = np.linspace(0, 0.4, thud_len, endpoint=False)
        thud[thud_idx:thud_idx + thud_len] = np.sin(2 * np.pi * 65.0 * np.exp(-6.0 * tt) * tt) * np.exp(-12.0 * tt) * 0.5

    env = np.sin(np.pi * np.clip(t / (duration * 0.95), 0.0, 1.0)) ** 0.8
    raw = (creak_body + wood_groan * groan_env) * env + thud

    reverbed = _apply_spatial_reverb(raw, sr, rt60=1.8, damp_freq=2200.0, wet=0.35, predelay_ms=25.0)
    return _finalize_audio(reverbed, drive=1.12)


def _synth_thunder(duration: float, sr: int) -> "np.ndarray":
    """Distant Thunder: Deep rolling thunderclap with atmospheric low-frequency absorption and cloud reverberations."""
    n = int(sr * duration)
    t = np.linspace(0, duration, n, endpoint=False)

    brown = _get_brown_noise(n, sr)

    # 1. Initial lightning strike & shockwave
    crack_noise = _apply_fft_filter(brown, sr, low_pass=320.0, high_pass=30.0, peaks=[(65, 3.0, 2.5), (120, 4.0, 1.5)])
    crack_env = np.exp(-2.2 * t)
    initial_strike = (crack_noise / np.std(crack_noise)) * crack_env * 0.7

    boom_f = 44.0 * np.exp(-0.25 * t)
    sub_boom = 0.5 * np.sin(2 * np.pi * np.cumsum(boom_f) / sr) * np.exp(-1.4 * t)

    # 2. Rolling turbulent reverberations across sky
    roll_mod = (
        0.35 * np.exp(-0.5 * ((t - 0.7) / 0.4) ** 2) +
        0.45 * np.exp(-0.5 * ((t - 1.4) / 0.5) ** 2) +
        0.30 * np.exp(-0.5 * ((t - 2.1) / 0.6) ** 2) +
        0.18 * np.exp(-0.5 * ((t - 2.8) / 0.7) ** 2)
    )
    rolling_rumble = _apply_fft_filter(brown, sr, low_pass=140.0, high_pass=25.0, peaks=[(48, 3.5, 2.0)])
    rolling_rumble = (rolling_rumble / np.std(rolling_rumble)) * roll_mod * 0.65

    raw = initial_strike + sub_boom + rolling_rumble
    reverbed = _apply_spatial_reverb(raw, sr, rt60=3.0, damp_freq=900.0, wet=0.50, predelay_ms=45.0)
    return _finalize_audio(reverbed, drive=1.2)


def _synth_evil_laugh(duration: float, sr: int) -> "np.ndarray":
    """Gargoyle Chuckle: Guttural monster chuckle with vocal tract formants, subharmonic gravel, and courtyard echo."""
    n = int(sr * duration)
    t = np.linspace(0, duration, n, endpoint=False)

    chuckles = [
        (0.10, 0.40, 115.0, 1.0),   # Hwaaa (opening big laugh)
        (0.60, 0.30, 105.0, 0.85),  # Ha
        (0.98, 0.28, 96.0,  0.80),  # Ha
        (1.35, 0.26, 88.0,  0.75),  # Ha
        (1.72, 0.35, 80.0,  0.70),  # Heh... (trailing raspy sigh)
    ]

    laugh = np.zeros(n, dtype=np.float64)
    for start_t, length, f_base, gain in chuckles:
        idx = int(start_t * sr)
        p_len = min(n - idx, int(length * sr))
        if p_len <= 0 or idx >= n:
            continue
        tp = np.linspace(0, length, p_len, endpoint=False)

        pitch = f_base - 18.0 * (tp / length)
        phase = 2 * np.pi * np.cumsum(pitch) / sr

        glottal = (
            np.sin(phase) +
            0.50 * np.sin(phase * 2) +
            0.30 * np.sin(phase * 3) +
            0.35 * np.sin(phase * 0.5)  # Demonic gravel subharmonic
        )

        formants = [(440, 4.5, 2.8), (1120, 5.5, 2.2), (2300, 6.5, 1.4)]
        vocal = _apply_fft_filter(glottal, sr, low_pass=3400.0, high_pass=120.0, peaks=formants)
        vocal = (vocal / np.std(vocal))

        aspiration = np.random.normal(0, 0.2, p_len)
        aspiration = _apply_fft_filter(aspiration, sr, low_pass=2800.0, high_pass=350.0)
        aspiration = (aspiration / np.std(aspiration)) * 0.25

        env_burst = np.sin(np.pi * (tp / length)) ** 1.6
        laugh[idx:idx + p_len] += (vocal * 0.75 + aspiration * 0.25) * env_burst * gain * 0.45

    reverbed = _apply_spatial_reverb(laugh, sr, rt60=2.4, damp_freq=2400.0, wet=0.42, predelay_ms=28.0)
    return _finalize_audio(reverbed, drive=1.12)


def _synth_generic_mystery(duration: float, sr: int) -> "np.ndarray":
    """Atmospheric gothic mystery stinger fallback for custom or unmapped sound effects."""
    n = int(sr * duration)
    t = np.linspace(0, duration, n, endpoint=False)

    # Low gothic drone (D2 73.4Hz + A2 110Hz + D3 146.8Hz)
    drone = 0.4 * np.sin(2 * np.pi * 73.4 * t) + 0.3 * np.sin(2 * np.pi * 110.0 * t) + 0.2 * np.sin(2 * np.pi * 146.8 * t)
    # Bell harmonic shimmer
    shimmer = 0.25 * np.sin(2 * np.pi * 880.0 * t) * np.exp(-1.5 * t) + 0.15 * np.sin(2 * np.pi * 1318.5 * t) * np.exp(-2.2 * t)
    # Filtered graveyard wind swell
    brown = _get_brown_noise(n, sr)
    wind = _apply_fft_filter(brown, sr, low_pass=350.0, high_pass=60.0)
    wind_env = np.sin(np.pi * np.clip(t / duration, 0.0, 1.0)) ** 1.2
    wind_layer = (wind / np.std(wind)) * wind_env * 0.35

    env = np.exp(-0.8 * t)
    raw = (drone * env + shimmer + wind_layer)
    reverbed = _apply_spatial_reverb(raw, sr, rt60=2.2, damp_freq=2200.0, wet=0.40, predelay_ms=25.0)
    return _finalize_audio(reverbed, drive=1.1)


# Mapping of profile keys to specialized synthesizers
PROCEDURAL_SYNTHESIZERS = {
    "motion_detected": _synth_motion_detected,
    "riddle_intro": _synth_riddle_intro,
    "correct_answer": _synth_correct_answer,
    "wrong_answer": _synth_wrong_answer,
    "silence_ghost": _synth_silence_ghost,
    "chains": _synth_chains,
    "creaky_door": _synth_creaky_door,
    "thunder": _synth_thunder,
    "evil_laugh": _synth_evil_laugh,
}


def synthesize_procedural_fx(name: str, out_wav: Path, duration: float = None) -> bool:
    """
    Synthesize high-fidelity Halloween audio stingers mathematically using NumPy.

    Constructs multi-layered acoustic waveforms at 44.1 kHz using physical modeling
    of bells, stone friction, stick-slip wood creaks, celesta sparkles, bronze gongs,
    gargoyle vocal tract formants, and power-of-2 fast convolution reverb.
    Generates studio-grade stingers in under 50 milliseconds with zero external assets.

    Args:
        name (str): Identifier key of the sound effect profile to generate.
        out_wav (Path): Target path where the resulting 16-bit PCM WAV will be written.
        duration (float, optional): Length in seconds. Defaults to profile duration.

    Returns:
        bool: True if synthesis succeeded and the WAV was saved; False on error.
    """
    if np is None:
        print("Error: numpy is required for audio synthesis.")
        return False

    sr = 44100
    if duration is None:
        profile = DEFAULT_FX_PROFILES.get(name, {})
        duration = profile.get("duration", 3.0)

    synth_fn = PROCEDURAL_SYNTHESIZERS.get(name, _synth_generic_mystery)
    audio = synth_fn(duration, sr)

    # Convert floating point samples to standard 16-bit signed PCM
    pcm_data = (audio * 32767).astype(np.int16)

    try:
        with wave.open(str(out_wav), "wb") as wf:
            wf.setnchannels(1)      # Mono channel
            wf.setsampwidth(2)     # 16 bits = 2 bytes per sample
            wf.setframerate(sr)    # 44100 Hz sampling rate
            wf.writeframes(pcm_data.tobytes())
        return True
    except Exception as e:
        print(f"Error saving synthesized WAV {out_wav}: {e}")
        return False


def generate_with_audiocraft(prompt: str, out_wav: Path, duration: float = 3.5,
                             model_name: str = "facebook/audiogen-medium") -> bool:
    """
    Generate an atmospheric sound effect using Meta's AudioCraft (AudioGen).

    Args:
        prompt (str): Text prompt describing the desired sound effect.
        out_wav (Path): Path where the resulting WAV should be saved.
        duration (float): Duration in seconds to generate. Defaults to 3.5.
        model_name (str): Pre-trained model ID on HuggingFace Hub. Defaults to 'facebook/audiogen-medium'.

    Returns:
        bool: True if AudioCraft generated and saved the file; False on failure or if audiocraft is not installed.
    """
    if not AUDIOCRAFT_AVAILABLE:
        print("Notice: audiocraft is not installed. Falling back to built-in procedural audio engine.")
        return False

    try:
        print(f"Loading AudioCraft model '{model_name}'...")
        model = AudioGen.get_pretrained(model_name)
        model.set_generation_params(duration=duration)
        print(f"Generating AudioCraft sound effect: \"{prompt}\"...")
        wav = model.generate([prompt])
        one_wav = wav[0].cpu()

        base_path = str(out_wav).replace(".wav", "")
        audio_write(
            base_path,
            one_wav,
            model.sample_rate,
            strategy="loudness",
            loudness_compressor=True
        )
        return out_wav.exists()
    except Exception as e:
        print(f"AudioCraft generation failed: {e}")
        return False


def generate_sound_effect(name: str, force_regenerate: bool = False, use_audiocraft: bool = False) -> Optional[Path]:
    """
    Ensure a sound effect is available in the cache, generating it if missing.

    Resolution Pipeline:
      1. Checks if an MP3 or WAV version is already cached (unless force_regenerate=True).
      2. If missing, attempts AudioCraft neural synthesis if requested and installed.
      3. Falls back to the procedural sound engine for instantaneous synthesis.
      4. Transcodes generated WAV to MP3 using ffmpeg for lightweight storage and fast streaming.

    Args:
        name (str): Identifier key of the sound effect (e.g. 'motion_detected', 'riddle_intro').
        force_regenerate (bool): If True, ignores existing cache and regenerates. Defaults to False.
        use_audiocraft (bool): If True and audiocraft is available, uses AudioGen. Defaults to False.

    Returns:
        Optional[Path]: Path to the ready-to-play MP3 (or WAV) file, or None if generation failed.
    """
    mp3_path = get_fx_path(name, "mp3")
    wav_path = get_fx_path(name, "wav")

    # Fast path: return existing cached audio if available
    if not force_regenerate:
        if mp3_path.exists() and mp3_path.stat().st_size > 1024:
            return mp3_path
        if wav_path.exists() and wav_path.stat().st_size > 1024:
            return wav_path

    profile = DEFAULT_FX_PROFILES.get(name, {
        "title": name,
        "prompt": f"spooky Halloween sound effect: {name}",
        "duration": 3.0
    })

    print(f"  [FX Cache Miss] Generating sound effect '{name}' ({profile['title']})...")

    success = False
    if use_audiocraft and AUDIOCRAFT_AVAILABLE:
        success = generate_with_audiocraft(profile["prompt"], wav_path, duration=profile["duration"])

    if not success:
        success = synthesize_procedural_fx(name, wav_path, duration=profile["duration"])

    if success and wav_path.exists():
        if convert_wav_to_mp3(wav_path, mp3_path):
            return mp3_path
        return wav_path

    return None


def prewarm_sound_effects(use_audiocraft: bool = False, force: bool = False) -> Dict[str, Path]:
    """
    Pre-generate and cache all standard Halloween Doorcam sound effects.

    Iterates over all keys in DEFAULT_FX_PROFILES and verifies they are rendered
    and cached. This eliminates runtime latency during live doorcam interactions.

    Args:
        use_audiocraft (bool): Whether to attempt neural AudioCraft generation
                               for missing effects. Defaults to False.
        force (bool): If True, forces regeneration of all effects even if cached.

    Returns:
        Dict[str, Path]: Dictionary mapping sound effect keys to their cached Paths.
    """
    action = "Regenerating" if force else "Pre-warming"
    print(f"{action} Halloween sound effects cache...")
    results = {}
    for fx_name in DEFAULT_FX_PROFILES.keys():
        path = generate_sound_effect(fx_name, force_regenerate=force, use_audiocraft=use_audiocraft)
        if path:
            results[fx_name] = path
            print(f"  ✓ Cached '{fx_name}' -> {path.name} ({path.stat().st_size // 1024} KB)")
        else:
            print(f"  ✗ Failed to generate '{fx_name}'")
    print("Sound effects cache pre-warm complete.")
    return results


def find_system_audio_player(prefer_pulse: bool = True) -> Optional[List[str]]:
    """
    Locate an available command-line audio player executable on the host or inside Docker.

    Checks the system PATH in order of preference:
      1. `pw-play` - Native PipeWire client (ideal on modern Linux hosts).
      2. `mpg123` - Primary lightweight MP3 player with direct PulseAudio/ALSA backend flags.
      3. `ffplay` - FFmpeg player (headless mode).
      4. `paplay` - PulseAudio WAV/audio player.
      5. `aplay` - ALSA native PCM player.

    Args:
        prefer_pulse (bool): If True and mpg123 is found, appends ['-o', 'pulse']. Defaults to True.

    Returns:
        Optional[List[str]]: Base command list suitable for subprocess.run, or None if no player found.
    """
    if shutil.which("pw-play"):
        return ["pw-play"]
    if shutil.which("mpg123"):
        cmd = ["mpg123", "-q"]
        if prefer_pulse:
            cmd.extend(["-o", "pulse"])
        return cmd
    if shutil.which("ffplay"):
        return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"]
    if shutil.which("paplay"):
        return ["paplay"]
    if shutil.which("aplay"):
        return ["aplay", "-q"]
    return None


def play_sound_effect(name: str, pulse_server: str = None, audio_output_device: str = None, wait: bool = True) -> bool:
    """
    Play a Halloween sound effect through the configured system or Docker audio output.

    Retrieves or generates the cached sound file, detects the appropriate system
    player, routes audio to the specified PulseAudio server or ALSA sink, and
    executes playback either synchronously (blocking) or asynchronously.

    Args:
        name (str): Sound effect identifier key (e.g. 'motion_detected', 'correct_answer').
        pulse_server (str, optional): PulseAudio server socket (e.g. 'unix:/tmp/pulse-socket').
        audio_output_device (str, optional): ALSA device string (e.g. 'hw:1,0') if not using PulseAudio.
        wait (bool): If True, blocks until playback finishes. If False, launches in background. Defaults to True.

    Returns:
        bool: True if playback launched/completed without error; False on failure.
    """
    fx_path = generate_sound_effect(name)
    if not fx_path or not fx_path.exists():
        return False

    prefer_pulse = bool(pulse_server or os.getenv("PULSE_SERVER"))
    player = find_system_audio_player(prefer_pulse=prefer_pulse)

    if not player:
        player = ["mpg123", "-q"]
        if prefer_pulse:
            player.extend(["-o", "pulse"])

    cmd = list(player)
    # If audio output device is specified and player is mpg123 (and not using Pulse server)
    if audio_output_device and audio_output_device.lower() not in ("default", "none") and "mpg123" in cmd[0] and not prefer_pulse:
        cmd.extend(["-a", audio_output_device])

    # If the player is pw-play, aplay or paplay, ensure we pass the WAV format (pw-play/aplay/paplay parse WAV natively)
    wav_path = get_fx_path(name, "wav")
    if cmd[0] in ("pw-play", "aplay", "paplay") and wav_path.exists() and wav_path.stat().st_size > 1024:
        cmd.append(str(wav_path))
    else:
        cmd.append(str(fx_path))

    try:
        if wait:
            subprocess.run(cmd, check=True)
        else:
            subprocess.Popen(cmd)
        return True
    except Exception as e:
        print(f"Error in sound effect playback ({name}): {e}")
        return False
