#!/usr/bin/env python3
"""
🎃 Halloween Doorcam - High-Quality Sound Effects Downloader & Masterer
======================================================================
Downloads authentic, broadcast-quality studio horror recordings (44.1kHz / 48kHz,
16/24-bit masters) from verified open source libraries (Little Robot Sound Factory,
SoundBible/Mike Koenig, Pro Tools masters, and Internet Archive) and masters them
into standardized, broadcast-ready WAV and MP3 files for the Halloween Doorcam.
"""

import os
import sys
import shutil
import zipfile
import urllib.request
import subprocess
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SCRATCH_DIR = SCRIPT_DIR / "scratch"
DOWNLOADS_DIR = SCRATCH_DIR / "downloads"
HORROR_PACK_DIR = SCRATCH_DIR / "horror_pack"
FX_DIR = SCRIPT_DIR / "audio_cache" / "fx"

DOWNLOAD_SOURCES = {
    # SoundBible & Open Masters (Mike Koenig / Richard Humphries 44.1/48kHz masters)
    "bell.wav": "https://raw.githubusercontent.com/fagnercarvalho/go-spooky-sounds/master/sounds/bell.wav",
    "laugh.wav": "https://raw.githubusercontent.com/fagnercarvalho/go-spooky-sounds/master/sounds/laugh.wav",
    "hauntedhouse.wav": "https://raw.githubusercontent.com/fagnercarvalho/go-spooky-sounds/master/sounds/hauntedhouse.wav",
    "witches.wav": "https://raw.githubusercontent.com/fagnercarvalho/go-spooky-sounds/master/sounds/witches.wav",
    "gong_deep.wav": "https://upload.wikimedia.org/wikipedia/commons/1/16/240382_the-very-real-horst_chinese-gong-finish-session-2014-06-10-29-143.wav",
    "thunder_nosferatu.wav": "https://upload.wikimedia.org/wikipedia/commons/a/ac/Nosferatu_thunderclap_-_Richard_Humphries.wav",
    "chains_archive.mp3": "https://archive.org/download/spookstuff/05%20Heavy%20Footsteps%20with%20Chains.mp3",
    "creaky_door_archive.mp3": "https://archive.org/download/spookstuff/03%20Creaking%20Heavy%20Door%20%28Wooden%29%2C%20Open%20and%20Close.mp3"
}

HORROR_PACK_URL = "https://opengameart.org/sites/default/files/Horror%20Sound%20Library.zip"


def download_file(url: str, dest: Path) -> bool:
    """Download a file with user agent and progress."""
    if dest.exists() and dest.stat().st_size > 1024:
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  Downloading {dest.name}...")
    req = urllib.request.Request(url, headers={"User-Agent": "HalloweenDoorcam/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp, open(dest, "wb") as out:
            shutil.copyfileobj(resp, out)
        return True
    except Exception as e:
        print(f"  Error downloading {dest.name}: {e}")
        return False


def setup_sources():
    """Ensure all raw audio source masters are downloaded and unpacked."""
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    for filename, url in DOWNLOAD_SOURCES.items():
        download_file(url, DOWNLOADS_DIR / filename)

    # Download & extract Little Robot Sound Factory pack
    zip_path = HORROR_PACK_DIR / "Horror_Sound_Library.zip"
    extracted_dir = HORROR_PACK_DIR / "extracted"
    if not (extracted_dir / "Horror Sound Library").exists():
        download_file(HORROR_PACK_URL, zip_path)
        print("  Extracting Horror Sound Library pack...")
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(extracted_dir)


def master_all_effects():
    """Master all effects to studio-quality 44.1kHz stereo WAV and 256kbps MP3."""
    setup_sources()
    FX_DIR.mkdir(parents=True, exist_ok=True)

    pack_wav = HORROR_PACK_DIR / "extracted" / "Horror Sound Library" / "Wav"

    effects = {
        "motion_detected": [
            "ffmpeg", "-y",
            "-i", str(pack_wav / "Gate_Open_00.wav"),
            "-i", str(pack_wav / "Monster_00.wav"),
            "-i", str(pack_wav / "Ambience_Hell_00.wav"),
            "-filter_complex",
            "[0:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,volume=1.2[gate];"
            "[1:a]adelay=300|300,aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,volume=0.9[growl];"
            "[2:a]atrim=0:3.5,asetpts=PTS-STARTPTS,aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,volume=0.35[rumble];"
            "[gate][growl][rumble]amix=inputs=3:duration=first:dropout_transition=2,afade=t=in:ss=0:d=0.05,afade=t=out:st=2.7:d=0.6,loudnorm=I=-16:TP=-1.0:LRA=11[out]",
            "-map", "[out]", "-ar", "44100", "-ac", "2"
        ],
        "riddle_intro": [
            "ffmpeg", "-y",
            "-i", str(DOWNLOADS_DIR / "bell.wav"),
            "-i", str(pack_wav / "Laugh_Evil_00.wav"),
            "-filter_complex",
            "[0:a]atrim=0:3.6,asetpts=PTS-STARTPTS,aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,volume=1.0[bell];"
            "[1:a]adelay=1100|1100,aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,volume=0.85[laugh];"
            "[bell][laugh]amix=inputs=2:duration=first:dropout_transition=2,afade=t=out:st=3.0:d=0.5,loudnorm=I=-16:TP=-1.0:LRA=11[out]",
            "-map", "[out]", "-ar", "44100", "-ac", "2"
        ],
        "correct_answer": [
            "ffmpeg", "-y",
            "-i", str(pack_wav / "Jingle_Win_00.wav"),
            "-filter_complex",
            "atrim=0:3.5,asetpts=PTS-STARTPTS,aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,afade=t=out:st=2.9:d=0.6,loudnorm=I=-16:TP=-1.0:LRA=11",
            "-ar", "44100", "-ac", "2"
        ],
        "wrong_answer": [
            "ffmpeg", "-y",
            "-i", str(DOWNLOADS_DIR / "gong_deep.wav"),
            "-i", str(pack_wav / "Jingle_Lose_00.wav"),
            "-filter_complex",
            "[0:a]atrim=0:3.4,asetpts=PTS-STARTPTS,aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,volume=1.1[gong];"
            "[1:a]adelay=300|300,atrim=0:3.1,asetpts=PTS-STARTPTS,aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,volume=0.75[lose];"
            "[gong][lose]amix=inputs=2:duration=first,afade=t=out:st=2.7:d=0.6,loudnorm=I=-16:TP=-1.0:LRA=11[out]",
            "-map", "[out]", "-ar", "44100", "-ac", "2"
        ],
        "silence_ghost": [
            "ffmpeg", "-y",
            "-i", str(DOWNLOADS_DIR / "hauntedhouse.wav"),
            "-i", str(pack_wav / "Ambience_MurderofCrows_00.wav"),
            "-filter_complex",
            "[0:a]atrim=0:3.5,asetpts=PTS-STARTPTS,aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,volume=1.0[ghost];"
            "[1:a]atrim=0:3.5,asetpts=PTS-STARTPTS,aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,volume=0.45[crows];"
            "[ghost][crows]amix=inputs=2:duration=first,afade=t=in:ss=0:d=0.1,afade=t=out:st=2.8:d=0.6,loudnorm=I=-16:TP=-1.0:LRA=11[out]",
            "-map", "[out]", "-ar", "44100", "-ac", "2"
        ],
        "chains": [
            "ffmpeg", "-y",
            "-i", str(DOWNLOADS_DIR / "chains_archive.mp3"),
            "-filter_complex",
            "atrim=0:3.2,asetpts=PTS-STARTPTS,aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,afade=t=in:ss=0:d=0.05,afade=t=out:st=2.6:d=0.5,loudnorm=I=-16:TP=-1.0:LRA=11",
            "-ar", "44100", "-ac", "2"
        ],
        "creaky_door": [
            "ffmpeg", "-y",
            "-i", str(DOWNLOADS_DIR / "creaky_door_archive.mp3"),
            "-filter_complex",
            "atrim=0.2:3.5,asetpts=PTS-STARTPTS,aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,afade=t=in:ss=0:d=0.05,afade=t=out:st=2.8:d=0.5,loudnorm=I=-16:TP=-1.0:LRA=11",
            "-ar", "44100", "-ac", "2"
        ],
        "thunder": [
            "ffmpeg", "-y",
            "-i", str(DOWNLOADS_DIR / "thunder_nosferatu.wav"),
            "-filter_complex",
            "atrim=2.8:7.2,asetpts=PTS-STARTPTS,aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,afade=t=in:ss=0:d=0.08,afade=t=out:st=3.6:d=0.7,loudnorm=I=-16:TP=-1.0:LRA=11",
            "-ar", "44100", "-ac", "2"
        ],
        "evil_laugh": [
            "ffmpeg", "-y",
            "-i", str(DOWNLOADS_DIR / "laugh.wav"),
            "-filter_complex",
            "atrim=0:3.0,asetpts=PTS-STARTPTS,aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,afade=t=in:ss=0:d=0.05,afade=t=out:st=2.5:d=0.5,loudnorm=I=-16:TP=-1.0:LRA=11",
            "-ar", "44100", "-ac", "2"
        ],
        "witch_cackle": [
            "ffmpeg", "-y",
            "-i", str(DOWNLOADS_DIR / "witches.wav"),
            "-filter_complex",
            "atrim=0:3.5,asetpts=PTS-STARTPTS,aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,afade=t=out:st=2.9:d=0.5,loudnorm=I=-16:TP=-1.0:LRA=11",
            "-ar", "44100", "-ac", "2"
        ],
        "monster_roar": [
            "ffmpeg", "-y",
            "-i", str(pack_wav / "Monster_05.wav"),
            "-filter_complex",
            "atrim=0:3.5,asetpts=PTS-STARTPTS,aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,afade=t=out:st=2.9:d=0.5,loudnorm=I=-16:TP=-1.0:LRA=11",
            "-ar", "44100", "-ac", "2"
        ],
        "jumpscare": [
            "ffmpeg", "-y",
            "-i", str(pack_wav / "Scream_Male_00.wav"),
            "-i", str(pack_wav / "Monster_03.wav"),
            "-filter_complex",
            "[0:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,volume=0.9[scream];"
            "[1:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,volume=1.0[roar];"
            "[scream][roar]amix=inputs=2:duration=first,afade=t=out:st=2.5:d=0.5,loudnorm=I=-16:TP=-1.0:LRA=11[out]",
            "-map", "[out]", "-ar", "44100", "-ac", "2"
        ]
    }

    print("Mastering high-fidelity Halloween sound effects...")
    for name, cmd in effects.items():
        wav_out = FX_DIR / f"{name}.wav"
        mp3_out = FX_DIR / f"{name}.mp3"
        subprocess.run(cmd + [str(wav_out)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["ffmpeg", "-y", "-i", str(wav_out), "-codec:a", "libmp3lame", "-b:a", "256k", str(mp3_out)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"  ✓ {name}: {wav_out.stat().st_size // 1024} KB WAV, {mp3_out.stat().st_size // 1024} KB MP3")
    print("Done! All effects cached in audio_cache/fx/")


if __name__ == "__main__":
    master_all_effects()
