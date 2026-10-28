#!/usr/bin/env python3
"""
Halloween Doorcam Device Setup & Configuration Script
Detects webcams and Bluetooth audio devices, presents an interactive
selection menu, and updates the .env configuration file accordingly.
"""

import os
import sys
import re
import glob
import json
import shutil
import fcntl
import struct
import argparse
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.prompt import Prompt, Confirm
    from rich.text import Text
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


# V4L2 ioctl definitions for querying device capabilities directly
VIDIOC_QUERYCAP = 0x80685600  # _IOR('v', 0, struct v4l2_capability)
V4L2_CAP_VIDEO_CAPTURE = 0x00000001
V4L2_CAP_DEVICE_CAPS = 0x80000000


class TerminalUI:
    """
    Terminal user interface manager supporting rich styling and graceful ASCII fallback.

    Provides formatted banners, section headers, styled badges, and status messages.
    If the `rich` library is installed, outputs modern styled panels and colored glyphs;
    otherwise, falls back to clean, standardized plain-text markers.
    """

    def __init__(self):
        """
        Initialize the terminal UI manager.

        Constructs a Rich Console instance if rich is available; otherwise sets console to None.
        """
        self.console = Console() if RICH_AVAILABLE else None

    def print_banner(self) -> None:
        """
        Render the Halloween Doorcam startup banner.

        Displays a themed panel with border styling in Rich, or an ASCII divider box.
        """
        title = "🎃 Halloween Doorcam - Device Setup Wizard 🎃"
        subtitle = "Detect and configure Webcam, Bluetooth Audio & Microphone devices"
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
            print("=" * 64)
            print(f" {title} ")
            print(f" {subtitle} ")
            print("=" * 64)
            print()

    def print_section(self, title: str) -> None:
        """
        Render a styled section header dividing configuration stages.

        Args:
            title (str): The section title to display.
        """
        if self.console:
            self.console.print(f"\n[bold bright_cyan]─── {title} ───[/bold bright_cyan]")
        else:
            print(f"\n--- {title} ---")

    def print_success(self, msg: str) -> None:
        """
        Print a success confirmation message with a green checkmark badge.

        Args:
            msg (str): Informational success message.
        """
        if self.console:
            self.console.print(f"[bold green]✓[/bold green] {msg}")
        else:
            print(f"[SUCCESS] {msg}")

    def print_warning(self, msg: str) -> None:
        """
        Print an alert or caution warning message with a yellow badge.

        Args:
            msg (str): Warning description.
        """
        if self.console:
            self.console.print(f"[bold yellow]![/bold yellow] {msg}")
        else:
            print(f"[WARNING] {msg}")

    def print_error(self, msg: str) -> None:
        """
        Print an error message with a red cross badge.

        Args:
            msg (str): Error description.
        """
        if self.console:
            self.console.print(f"[bold red]✗[/bold red] {msg}")
        else:
            print(f"[ERROR] {msg}")

    def print_info(self, msg: str) -> None:
        """
        Print an informational hint or progress indicator.

        Args:
            msg (str): Information text.
        """
        if self.console:
            self.console.print(f"[dim blue]ℹ[/dim blue] {msg}")
        else:
            print(f"[INFO] {msg}")


ui = TerminalUI()


def query_v4l2_caps(device_path: str) -> Optional[Dict[str, Any]]:
    """
    Query Video4Linux2 kernel device capabilities directly using ioctl calls.

    Performs a low-level `VIDIOC_QUERYCAP` ioctl request against the given device
    node to inspect driver metadata and determine whether the device supports
    video capture (`V4L2_CAP_VIDEO_CAPTURE`). This allows distinguishing genuine
    webcam capture streams from metadata nodes (e.g. IR depth cameras or hardware
    compression sinks).

    Binary layout queried:
      struct v4l2_capability {
          __u8  driver[16];
          __u8  card[32];
          __u8  bus_info[32];
          __u32 version;
          __u32 capabilities;
          __u32 device_caps;
          __u32 reserved[3];
      };

    Args:
        device_path (str): Filesystem path to the V4L2 device node (e.g. '/dev/video0').

    Returns:
        Optional[Dict[str, Any]]: Dictionary containing:
            - 'path': Device filesystem path.
            - 'card': Human-readable device/card name.
            - 'driver': Kernel driver module name (e.g. 'uvcvideo').
            - 'bus_info': USB/PCI bus identifier.
            - 'is_capture': True if device possesses video capture capability.
            - 'can_access': True if readable and writable by current process.
            Or None if device could not be opened or queried.

    Example:
        >>> caps = query_v4l2_caps("/dev/video0")
        >>> if caps and caps["is_capture"]:
        ...     print("Valid webcam:", caps["card"])
    """
    try:
        fd = os.open(device_path, os.O_RDWR | os.O_NONBLOCK)
    except OSError:
        try:
            fd = os.open(device_path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            return None

    try:
        buf = bytearray(104)
        fcntl.ioctl(fd, VIDIOC_QUERYCAP, buf)
        driver, card, bus_info, version, capabilities, device_caps = struct.unpack("16s32s32sIII", buf[:92])
        
        card_str = card.split(b"\x00")[0].decode("utf-8", "ignore").strip()
        driver_str = driver.split(b"\x00")[0].decode("utf-8", "ignore").strip()
        bus_str = bus_info.split(b"\x00")[0].decode("utf-8", "ignore").strip()
        
        caps = device_caps if (capabilities & V4L2_CAP_DEVICE_CAPS) else capabilities
        is_capture = bool(caps & V4L2_CAP_VIDEO_CAPTURE)
        
        return {
            "path": device_path,
            "card": card_str,
            "driver": driver_str,
            "bus_info": bus_str,
            "is_capture": is_capture,
            "can_access": os.access(device_path, os.R_OK | os.W_OK)
        }
    except Exception:
        return None
    finally:
        os.close(fd)


def detect_webcams() -> List[Dict[str, Any]]:
    """
    Discover and enumerate all video capture webcams on the host Linux system.

    Scans `/dev/video*` character devices in numerical order, queries their V4L2
    capabilities to filter out non-capture metadata streams, extracts friendly
    names from `/sys/class/video4linux/`, and queries supported video formats
    (such as MJPG or YUYV) via `v4l2-ctl` when available.

    Returns:
        List[Dict[str, Any]]: List of discovered webcam metadata dictionaries:
            - 'path': Device path (e.g. '/dev/video2').
            - 'name': Clean human-readable camera model name.
            - 'driver': Driver name (e.g. 'uvcvideo').
            - 'bus_info': USB/PCI bus identifier.
            - 'sys_index': V4L2 device index (0 for primary capture stream).
            - 'formats': List of supported FourCC format strings (e.g. ['YUYV', 'MJPG']).
            - 'accessible': True if current user has read/write permissions.

    Example:
        >>> webcams = detect_webcams()
        >>> for cam in webcams:
        ...     print(cam['path'], cam['name'], cam['formats'])
    """
    detected = []
    video_paths = sorted(glob.glob("/dev/video*"), key=lambda p: int(re.search(r"\d+", p).group() if re.search(r"\d+", p) else 999))
    
    for path in video_paths:
        v4l2_info = query_v4l2_caps(path)
        
        # Read sysfs info if available
        base_name = os.path.basename(path)
        sys_dir = Path(f"/sys/class/video4linux/{base_name}")
        sys_name = ""
        sys_index = None
        if sys_dir.exists():
            name_file = sys_dir / "name"
            if name_file.exists():
                try:
                    sys_name = name_file.read_text().strip()
                except Exception:
                    pass
            idx_file = sys_dir / "index"
            if idx_file.exists():
                try:
                    sys_index = int(idx_file.read_text().strip())
                except Exception:
                    pass
                    
        # Determine friendly card name
        card_name = (v4l2_info.get("card") if v4l2_info else "") or sys_name or f"Camera ({base_name})"
        # Clean duplicated prefixes like 'UGREEN Camera: UGREEN Camera' or 'ASUS FHD webcam: ASUS FHD webca'
        if ":" in card_name:
            parts = [p.strip() for p in card_name.split(":") if p.strip()]
            if len(parts) >= 2:
                if parts[0] == parts[1] or parts[0].startswith(parts[1]) or parts[1].startswith(parts[0]):
                    card_name = parts[0] if len(parts[0]) >= len(parts[1]) else parts[1]
                
        is_capture = v4l2_info.get("is_capture", False) if v4l2_info else False
        
        # If ioctl was blocked by permissions, check sysfs index (index 0 is capture node)
        if not v4l2_info and sys_index == 0:
            is_capture = True
            
        if is_capture:
            # Query supported formats using v4l2-ctl if installed
            formats = []
            try:
                res = subprocess.run(["v4l2-ctl", "-d", path, "--list-formats"], capture_output=True, text=True, timeout=2)
                for line in res.stdout.splitlines():
                    fmt_match = re.search(r"'(....)'", line)
                    if fmt_match:
                        formats.append(fmt_match.group(1))
            except Exception:
                pass

            detected.append({
                "path": path,
                "name": card_name,
                "driver": v4l2_info.get("driver", "uvcvideo") if v4l2_info else "uvcvideo",
                "bus_info": v4l2_info.get("bus_info", "") if v4l2_info else "",
                "sys_index": sys_index if sys_index is not None else 0,
                "formats": formats,
                "accessible": os.access(path, os.R_OK | os.W_OK)
            })

    return detected


def check_bluetooth_status() -> Tuple[bool, str]:
    """
    Verify the operational status of the host system's primary Bluetooth controller.

    Executes `bluetoothctl show` to inspect the default Bluetooth adapter (BlueZ).
    Checks if BlueZ is responding and whether the radio power state is active.

    Returns:
        Tuple[bool, str]:
            - bool: True if the adapter is present and powered on; False otherwise.
            - str: Descriptive status message explaining state or diagnostic error.

    Example:
        >>> ok, message = check_bluetooth_status()
        >>> if not ok:
        ...     print("Bluetooth error:", message)
    """
    try:
        res = subprocess.run(["bluetoothctl", "show"], capture_output=True, text=True, timeout=3)
        if res.returncode != 0:
            return False, "bluetoothctl returned an error or BlueZ is not running."
        if "Powered: yes" in res.stdout:
            return True, "Bluetooth adapter is powered on."
        elif "Powered: no" in res.stdout:
            return False, "Bluetooth adapter is turned OFF."
        else:
            return False, "No active Bluetooth controller found."
    except FileNotFoundError:
        return False, "bluetoothctl is not installed on this system."
    except Exception as e:
        return False, f"Failed to check Bluetooth status: {e}"


def get_bluetooth_audio_devices() -> List[Dict[str, Any]]:
    """
    Enumerate paired, trusted, and connected Bluetooth audio peripherals.

    Discovers devices recognized by BlueZ (`bluetoothctl devices`), queries their
    detailed profiles via `bluetoothctl info <mac>`, and classifies them by
    inspecting Device Class flags (Audio/Video bitmask 0x0400), icons
    ('audio-headset', 'audio-speaker'), and UUID service definitions (Audio Sink,
    Audio Source, A2DP, Handsfree).

    Returns:
        List[Dict[str, Any]]: List of Bluetooth audio device records:
            - 'mac': Hardware MAC address (e.g. '4C:3C:8F:93:76:CE').
            - 'name': Clean human-friendly device alias or name.
            - 'raw_name': Factory advertised name.
            - 'icon': Device icon type.
            - 'paired': Boolean pairing state.
            - 'connected': Boolean connection state.
            - 'trusted': Boolean trust flag in BlueZ.
            - 'type_description': Descriptive role (e.g. 'Speaker / Output').
            - 'uuids': String of UUID service descriptions.

    Example:
        >>> bt_devices = get_bluetooth_audio_devices()
        >>> for dev in bt_devices:
        ...     print(dev['mac'], dev['name'], dev['connected'])
    """
    devices = []
    try:
        res = subprocess.run(["bluetoothctl", "devices"], capture_output=True, text=True, timeout=4)
    except Exception:
        return []

    lines = res.stdout.strip().splitlines()
    for line in lines:
        parts = line.split(" ", 2)
        if len(parts) >= 3 and parts[0] == "Device":
            mac = parts[1]
            default_name = parts[2]

            try:
                info_res = subprocess.run(["bluetoothctl", "info", mac], capture_output=True, text=True, timeout=4)
                info_text = info_res.stdout
            except Exception:
                info_text = ""

            # Parse device properties
            name_match = re.search(r"^\s*Name:\s*(.+)$", info_text, re.MULTILINE)
            name = name_match.group(1).strip() if name_match else default_name

            alias_match = re.search(r"^\s*Alias:\s*(.+)$", info_text, re.MULTILINE)
            alias = alias_match.group(1).strip() if alias_match else name

            icon_match = re.search(r"^\s*Icon:\s*(.+)$", info_text, re.MULTILINE)
            icon = icon_match.group(1).strip() if icon_match else ""

            connected = False
            conn_match = re.search(r"^\s*Connected:\s*(yes|no)", info_text, re.MULTILINE | re.IGNORECASE)
            if conn_match:
                connected = (conn_match.group(1).lower() == "yes")

            paired = False
            paired_match = re.search(r"^\s*Paired:\s*(yes|no)", info_text, re.MULTILINE | re.IGNORECASE)
            if paired_match:
                paired = (paired_match.group(1).lower() == "yes")

            trusted = False
            trusted_match = re.search(r"^\s*Trusted:\s*(yes|no)", info_text, re.MULTILINE | re.IGNORECASE)
            if trusted_match:
                trusted = (trusted_match.group(1).lower() == "yes")

            # Extract UUIDs and service classes
            uuids = re.findall(r"^\s*UUID:\s*([^\(]+)", info_text, re.MULTILINE)
            uuid_text = " ".join(u.strip() for u in uuids)

            # Determine device audio classification
            is_audio = False
            audio_types = []

            if "audio-headset" in icon or "audio-headphones" in icon or "audio-card" in icon or "audio-speaker" in icon:
                is_audio = True

            if "Audio Sink" in info_text:
                is_audio = True
                audio_types.append("Speaker / Output")
            if "Audio Source" in info_text:
                is_audio = True
                audio_types.append("Audio Source")
            if "Handsfree" in info_text or "Headset" in info_text:
                is_audio = True
                audio_types.append("Mic / Headset")

            # Check class of device if icon/UUID was ambiguous
            class_match = re.search(r"^\s*Class:\s*(0x[0-9a-fA-F]+)", info_text, re.MULTILINE)
            if class_match:
                cod = int(class_match.group(1), 16)
                # Major Device Class: Audio/Video is bits 8-12 == 0x0400
                if (cod & 0x1F00) == 0x0400:
                    is_audio = True

            if is_audio:
                devices.append({
                    "mac": mac,
                    "name": alias or name,
                    "raw_name": name,
                    "icon": icon or "audio-headset",
                    "paired": paired,
                    "connected": connected,
                    "trusted": trusted,
                    "type_description": ", ".join(audio_types) if audio_types else "Bluetooth Audio Device",
                    "uuids": uuid_text
                })

    return devices


def set_default_bluetooth_sink(device_name: str = "") -> None:
    """
    Configure PipeWire to route system audio output to the specified Bluetooth sink.

    Queries `wpctl status` for registered audio sinks. If `device_name` is provided,
    searches for matching sink lines; otherwise searches for known Bluetooth sink
    identifiers (e.g. 'bluez', 'speaker', 'soundcore'). Sets the active sink via
    `wpctl set-default <id>`.

    Args:
        device_name (str, optional): Target device name or substring. Defaults to "".

    Returns:
        None

    Example:
        >>> set_default_bluetooth_sink("JBL Clip 5")
    """
    try:
        res = subprocess.run(["wpctl", "status"], capture_output=True, text=True, timeout=3)
        sink_id = None
        target = device_name.lower() if device_name else ""
        for line in res.stdout.splitlines():
            clean = line.lower()
            if "[vol:" in clean:
                if target and target in clean:
                    m = re.search(r"(\d+)\.\s+", line)
                    if m:
                        sink_id = m.group(1)
                        break
                elif not target and ("bluez" in clean or "soundcore" in clean or "headset" in clean or "speaker" in clean):
                    m = re.search(r"(\d+)\.\s+", line)
                    if m:
                        sink_id = m.group(1)
                        break
        if sink_id:
            subprocess.run(["wpctl", "set-default", sink_id], capture_output=True, timeout=3)
    except Exception:
        pass


def connect_bluetooth_device(mac: str, timeout: int = 8) -> Tuple[bool, str]:
    """
    Initiate an RFCOMM / A2DP connection to a Bluetooth device using bluetoothctl.

    Invokes `bluetoothctl connect <MAC>` with a configurable timeout. If successful,
    automatically updates the PipeWire default audio sink.

    Args:
        mac (str): MAC address of the target Bluetooth device (e.g. '4C:3C:8F:93:76:CE').
        timeout (int): Maximum connection attempt timeout in seconds. Defaults to 8.

    Returns:
        Tuple[bool, str]:
            - bool: True if connection succeeded or device was already connected; False on error.
            - str: Descriptive status message or error text.

    Example:
        >>> ok, err = connect_bluetooth_device("4C:3C:8F:93:76:CE", timeout=10)
    """
    try:
        res = subprocess.run(["bluetoothctl", "connect", mac], capture_output=True, text=True, timeout=timeout)
        output = (res.stdout + "\n" + res.stderr).strip()
        if "Connection successful" in output or "already connected" in output.lower():
            set_default_bluetooth_sink()
            return True, "Connected successfully."
        else:
            first_err = output.splitlines()[-1] if output else "Connection failed"
            return False, first_err
    except subprocess.TimeoutExpired:
        return False, f"Connection timed out after {timeout} seconds (device may be powered off or out of range)."
    except Exception as e:
        return False, str(e)


def scan_bluetooth_devices(timeout: int = 8) -> None:
    """
    Perform an active Bluetooth LE and classic discovery scan for nearby devices.

    Executes `bluetoothctl --timeout <timeout> scan on` to broadcast inquiry packets
    and populate BlueZ's cache with newly discoverable devices.

    Args:
        timeout (int): Scan duration in seconds. Defaults to 8.

    Returns:
        None

    Example:
        >>> scan_bluetooth_devices(timeout=5)
    """
    ui.print_info(f"Scanning for nearby Bluetooth devices ({timeout}s)... Put your headset in pairing mode.")
    try:
        subprocess.run(["bluetoothctl", "--timeout", str(timeout), "scan", "on"], capture_output=True, text=True)
    except Exception as e:
        ui.print_warning(f"Scan interrupted or failed: {e}")


def set_default_pipewire_source(source_id: str) -> None:
    """
    Set the default system audio recording source node in PipeWire.

    Executes `wpctl set-default <source_id>` so all recording applications (and
    Docker PulseAudio bridges) capture audio from the designated input device.

    Args:
        source_id (str): Integer node ID from `wpctl status` (e.g. '53').

    Returns:
        None

    Example:
        >>> set_default_pipewire_source("53")
    """
    try:
        subprocess.run(["wpctl", "set-default", str(source_id)], capture_output=True, timeout=3)
    except Exception:
        pass


def detect_audio_input_devices() -> List[Dict[str, Any]]:
    """
    Discover all available audio input (microphone) devices via PipeWire and ALSA.

    Probes the audio subsystem in two phases:
      1. PipeWire Sources (`wpctl status`): Parses the 'Sources:' section to extract
         active audio recording nodes, their numeric node IDs, volume levels, default
         status (* marker), and classifies their role (e.g. 'Webcam Mic', 'Wireless Mic',
         'Headset Mic', 'Built-in Mic').
      2. ALSA Fallback (`arecord -l`): If PipeWire returns no sources (e.g. in container
         or bare ALSA environments), probes hardware ALSA soundcards and capture subdevices.

    Returns:
        List[Dict[str, Any]]: List of discovered microphone dictionaries:
            - 'id': PipeWire node ID (e.g. '53') or ALSA device string ('hw:2,0').
            - 'name': Friendly device name (e.g. 'Wireless Microphone Analog Stereo').
            - 'type': Inferred device role ('Wireless Mic', 'Webcam Mic', etc.).
            - 'default': True if flagged as system default input source.
            - 'system': Audio subsystem origin ('pipewire' or 'alsa').

    Example:
        >>> mics = detect_audio_input_devices()
        >>> for mic in mics:
        ...     print(f"[{mic['id']}] {mic['name']} ({mic['type']})")
    """
    devices = []
    seen_names = set()

    # 1. PipeWire sources via wpctl status
    try:
        res = subprocess.run(["wpctl", "status"], capture_output=True, text=True, timeout=3)
        in_sources = False
        for line in res.stdout.splitlines():
            clean = line.strip()
            if "Sources:" in clean:
                in_sources = True
                continue
            elif clean.startswith("Source endpoints:") or clean.startswith("Streams:") or clean.startswith("Settings:") or clean.startswith("Video"):
                in_sources = False
                continue

            if in_sources:
                m = re.search(r"(\*?)\s+(\d+)\.\s+(.+?)\s+\[vol:", line)
                if m:
                    is_default = bool(m.group(1))
                    node_id = m.group(2)
                    name = m.group(3).strip()

                    nl = name.lower()
                    if "camera" in nl or "webcam" in nl:
                        dev_type = "Webcam Mic"
                    elif "wireless" in nl:
                        dev_type = "Wireless Mic"
                    elif "headset" in nl or "headphone" in nl:
                        dev_type = "Headset Mic"
                    elif "digital" in nl or "internal" in nl or "dmic" in nl:
                        dev_type = "Built-in Mic"
                    elif "mic" in nl:
                        dev_type = "Microphone"
                    else:
                        dev_type = "Audio Source"

                    devices.append({
                        "id": node_id,
                        "name": name,
                        "type": dev_type,
                        "default": is_default,
                        "system": "pipewire"
                    })
                    seen_names.add(name.lower())
    except Exception:
        pass

    # 2. Check ALSA capture devices as fallback if no PipeWire sources were found
    if not devices:
        try:
            res = subprocess.run(["arecord", "-l"], capture_output=True, text=True, timeout=3)
            for line in res.stdout.splitlines():
                m = re.search(r"card\s+(\d+):\s+([^,]+),\s+device\s+(\d+):\s+([^\[]+)\[([^\]]+)\]", line)
                if m:
                    card_num, card_name, dev_num, _, dev_desc = m.groups()
                    card_name = card_name.strip()
                    dev_desc = dev_desc.strip()
                    full_name = f"{card_name} ({dev_desc})" if card_name != dev_desc else card_name
                    devices.append({
                        "id": f"hw:{card_num},{dev_num}",
                        "name": full_name,
                        "type": "ALSA Capture",
                        "default": False,
                        "system": "alsa"
                    })
        except Exception:
            pass

    return devices


def read_env_file(env_path: Path) -> Dict[str, str]:
    """
    Parse environment key-value pairs from a `.env` file into a dictionary.

    Reads the specified file, ignoring commented lines (starting with '#')
    and blank lines. Strips surrounding single or double quotes from values.

    Args:
        env_path (Path): Path to the target `.env` file.

    Returns:
        Dict[str, str]: Key-value mapping of configured environment variables.

    Example:
        >>> env_vars = read_env_file(Path(".env"))
        >>> print(env_vars.get("CAMERA_DEVICE"))
        /dev/video2
    """
    values = {}
    if not env_path.exists():
        return values
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    values[key.strip()] = val.strip().strip("'\"")
    except Exception:
        pass
    return values


def update_env_file(env_path: Path, updates: Dict[str, str]) -> bool:
    """
    Safely modify key-value pairs in a `.env` file with backup and comment preservation.

    Preserves existing comments, spacing, and variable ordering. Before writing changes,
    creates a backup copy (`.env.bak`). If a variable does not exist in the file, appends
    it under an appropriate logical section heading (e.g. Camera or Bluetooth & Audio).

    Args:
        env_path (Path): Path to the `.env` file to update.
        updates (Dict[str, str]): Dictionary of key-value pairs to set or replace.

    Returns:
        bool: True if file was updated successfully; False on I/O or permissions error.

    Example:
        >>> update_env_file(Path(".env"), {"CAMERA_DEVICE": "/dev/video0"})
        True
    """
    if env_path.exists():
        backup_path = env_path.with_name(f"{env_path.name}.bak")
        try:
            shutil.copy2(env_path, backup_path)
            ui.print_info(f"Created backup of {env_path.name} at: {backup_path.name}")
        except Exception as e:
            ui.print_warning(f"Could not create backup file: {e}")
            
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    else:
        # If no .env exists, look for .env.example
        example_path = env_path.parent / ".env.example"
        if example_path.exists():
            with open(example_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        else:
            lines = [
                "# =================================================================\n",
                "# Halloween Doorcam Configuration\n",
                "# =================================================================\n\n"
            ]

    # Track which keys we have updated
    remaining_keys = set(updates.keys())
    new_lines = []

    for line in lines:
        stripped = line.strip()
        matched_key = None
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k = stripped.split("=", 1)[0].strip()
            if k in updates:
                matched_key = k

        if matched_key:
            # Replace existing line with updated value
            val = updates[matched_key]
            new_lines.append(f"{matched_key}={val}\n")
            remaining_keys.remove(matched_key)
        else:
            new_lines.append(line)

    # If any keys remain to be added (e.g. BLUETOOTH_AUDIO_NAME, PULSE_SERVER)
    if remaining_keys:
        # Check if we should insert audio keys under an Audio & Bluetooth header
        audio_keys = {"BLUETOOTH_AUDIO_NAME", "BLUETOOTH_AUDIO_MAC", "AUDIO_OUTPUT_DEVICE", 
                      "AUDIO_INPUT_DEVICE", "PULSE_SERVER", "PULSE_SOCKET"}
        camera_keys = {"CAMERA_DEVICE", "CAMERA_NAME"}

        insert_audio = [k for k in remaining_keys if k in audio_keys]
        insert_camera = [k for k in remaining_keys if k in camera_keys]
        insert_other = [k for k in remaining_keys if k not in audio_keys and k not in camera_keys]

        if insert_camera:
            new_lines.append("\n# --- Camera Device Metadata ---\n")
            for k in insert_camera:
                new_lines.append(f"{k}={updates[k]}\n")

        if insert_audio:
            new_lines.append("\n# --- Bluetooth & Audio Configuration ---\n")
            for k in insert_audio:
                new_lines.append(f"{k}={updates[k]}\n")

        if insert_other:
            new_lines.append("\n# --- Additional Settings ---\n")
            for k in insert_other:
                new_lines.append(f"{k}={updates[k]}\n")

    try:
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        return True
    except Exception as e:
        ui.print_error(f"Failed to write to {env_path}: {e}")
        return False


def display_webcam_menu(webcams: List[Dict[str, Any]], current_device: str) -> Optional[Dict[str, Any]]:
    """
    Present an interactive selection menu of detected video capture webcams.

    Renders a Rich-formatted table (or plain text list) showing device nodes,
    camera model names, hardware drivers, and supported video formats. Highlights
    the currently configured camera and prompts the user to select by index or
    enter a custom `/dev/video*` path.

    Args:
        webcams (List[Dict[str, Any]]): List of discovered webcam metadata dicts.
        current_device (str): Currently configured CAMERA_DEVICE path from .env.

    Returns:
        Optional[Dict[str, Any]]: Selected webcam metadata dictionary, or None if cancelled.

    Example:
        >>> chosen = display_webcam_menu(webcams, "/dev/video2")
        >>> print(chosen["path"])
    """
    ui.print_section("Webcam Selection")
    
    if not webcams:
        ui.print_warning("No Video Capture webcams detected under /dev/video*.")
        ui.print_info("Make sure your webcam is plugged in and recognized via `ls -l /dev/video*`.")
        manual_path = input("Enter camera device path manually (or press Enter to keep current): ").strip()
        if manual_path:
            return {"path": manual_path, "name": "Manual Entry"}
        elif current_device:
            return {"path": current_device, "name": "Existing Configuration"}
        return None

    if RICH_AVAILABLE:
        table = Table(title="Detected Video Capture Webcams", show_header=True, header_style="bold magenta")
        table.add_column("#", style="dim", width=4)
        table.add_column("Device Node", style="cyan")
        table.add_column("Camera Name", style="bold white")
        table.add_column("Driver / Bus", style="dim")
        table.add_column("Formats", style="green")
        table.add_column("Status", justify="center")

        default_idx = 1
        for idx, cam in enumerate(webcams, 1):
            is_current = (cam["path"] == current_device)
            if is_current:
                default_idx = idx
                status = "[bold green]CURRENT[/bold green]"
            else:
                status = "[green]Ready[/green]" if cam["accessible"] else "[red]Check Perms[/red]"

            fmts = ", ".join(cam["formats"]) if cam["formats"] else "V4L2"
            bus = cam["bus_info"] or cam["driver"]
            table.add_row(str(idx), cam["path"], cam["name"], bus, fmts, status)

        ui.console.print(table)
    else:
        print("\nDetected Webcams:")
        default_idx = 1
        for idx, cam in enumerate(webcams, 1):
            current_tag = " [CURRENT]" if cam["path"] == current_device else ""
            if cam["path"] == current_device:
                default_idx = idx
            print(f" [{idx}] {cam['path']} - {cam['name']}{current_tag}")

    print()
    prompt_str = f"Select webcam [1-{len(webcams)}] (default: {default_idx}): "
    
    while True:
        try:
            choice = input(prompt_str).strip()
            if not choice:
                return webcams[default_idx - 1]
            if choice.isdigit() and 1 <= int(choice) <= len(webcams):
                return webcams[int(choice) - 1]
            if choice.startswith("/dev/video"):
                # Direct path entered
                return {"path": choice, "name": "Custom Video Device"}
            ui.print_warning(f"Invalid selection '{choice}'. Please enter a number between 1 and {len(webcams)}.")
        except (KeyboardInterrupt, EOFError):
            print()
            ui.print_info("Selection cancelled by user.")
            sys.exit(0)


def display_bluetooth_menu(bt_devices: List[Dict[str, Any]], current_mac: str) -> Tuple[Optional[Dict[str, Any]], bool]:
    """
    Present an interactive selection menu for Bluetooth audio devices.

    Lists paired and connected Bluetooth audio sinks (speakers and headsets),
    indicating connection status and highlighting the active MAC address.
    Supports selecting an existing device, initiating a discovery rescan,
    manual MAC entry, or skipping Bluetooth to use default system audio.

    Args:
        bt_devices (List[Dict[str, Any]]): List of detected Bluetooth audio peripherals.
        current_mac (str): Current BLUETOOTH_AUDIO_MAC address from .env.

    Returns:
        Tuple[Optional[Dict[str, Any]], bool]:
            - Optional[Dict[str, Any]]: Selected device dictionary, or None if skipped.
            - bool: True if the user requested a nearby Bluetooth discovery rescan.

    Example:
        >>> dev, rescan = display_bluetooth_menu(bt_devices, "4C:3C:8F:93:76:CE")
    """
    ui.print_section("Bluetooth Audio Device Selection")

    bt_ok, bt_msg = check_bluetooth_status()
    if not bt_ok:
        ui.print_warning(f"Bluetooth notice: {bt_msg}")

    if not bt_devices:
        ui.print_warning("No paired Bluetooth audio devices found.")
        ui.print_info("You can scan for nearby pairing devices or skip Bluetooth audio.")
    else:
        if RICH_AVAILABLE:
            table = Table(title="Detected Bluetooth Audio Devices", show_header=True, header_style="bold blue")
            table.add_column("#", style="dim", width=4)
            table.add_column("Device Name", style="bold white")
            table.add_column("MAC Address", style="cyan")
            table.add_column("Capabilities", style="dim")
            table.add_column("Status", justify="center")

            default_idx = 1
            for idx, dev in enumerate(bt_devices, 1):
                is_current = (dev["mac"].upper() == current_mac.upper())
                if is_current:
                    default_idx = idx

                if dev["connected"]:
                    status = "[bold green]● Connected[/bold green]"
                else:
                    status = "[yellow]○ Disconnected (Paired)[/yellow]"

                if is_current:
                    status += " [bold magenta][CURRENT][/bold magenta]"

                table.add_row(str(idx), dev["name"], dev["mac"], dev["type_description"], status)

            ui.console.print(table)
        else:
            print("\nDetected Bluetooth Audio Devices:")
            default_idx = 1
            for idx, dev in enumerate(bt_devices, 1):
                is_current = (dev["mac"].upper() == current_mac.upper())
                if is_current:
                    default_idx = idx
                status = "Connected" if dev["connected"] else "Disconnected (Paired)"
                current_tag = " [CURRENT]" if is_current else ""
                print(f" [{idx}] {dev['name']} ({dev['mac']}) - {status}{current_tag}")

    print("\nOptions:")
    num_devices = len(bt_devices)
    if num_devices > 0:
        print(f" [1-{num_devices}] Select a Bluetooth device from the list")
    print(" [0] Do NOT use Bluetooth (use system default audio / USB mic)")
    print(" [s] Scan for nearby Bluetooth devices (put your device in pairing mode)")
    print(" [m] Enter Bluetooth MAC address manually")

    default_choice = "1" if num_devices > 0 else "0"
    prompt_str = f"Choose option (default: {default_choice}): "

    while True:
        try:
            choice = input(prompt_str).strip().lower()
            if not choice:
                choice = default_choice

            if choice == "s":
                return None, True
            elif choice == "0" or choice == "none":
                return None, False
            elif choice == "m":
                mac = input("Enter Bluetooth MAC address (e.g. AA:BB:CC:DD:EE:FF): ").strip()
                name = input("Enter device name (optional): ").strip() or "Custom Bluetooth Device"
                return {"mac": mac, "name": name, "connected": False}, False
            elif choice.isdigit() and 1 <= int(choice) <= num_devices:
                return bt_devices[int(choice) - 1], False
            else:
                ui.print_warning(f"Invalid option '{choice}'.")
        except (KeyboardInterrupt, EOFError):
            print()
            ui.print_info("Selection cancelled by user.")
            sys.exit(0)


def display_audio_input_menu(
    audio_inputs: List[Dict[str, Any]],
    current_input: str,
    selected_bt: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Present an interactive selection menu for audio recording inputs (microphones).

    Displays PipeWire sources and ALSA recording nodes, highlighting active and
    system default inputs. Provides shortcuts to use a paired Bluetooth headset mic,
    the system default recording stream, or manual string entry.

    Args:
        audio_inputs (List[Dict[str, Any]]): List of discovered microphone dicts.
        current_input (str): Current AUDIO_INPUT_DEVICE setting from .env.
        selected_bt (Optional[Dict[str, Any]]): Currently selected Bluetooth peripheral.

    Returns:
        Dict[str, Any]: Dictionary containing selected microphone name, ID, and type.

    Example:
        >>> mic = display_audio_input_menu(audio_inputs, "Wireless Microphone")
        >>> print(mic["name"])
    """
    ui.print_section("Audio Input Device (Microphone) Selection")

    if not audio_inputs:
        ui.print_warning("No audio input / microphone devices detected automatically.")
        manual_name = input("Enter microphone device name (or press Enter for 'default'): ").strip()
        return {"name": manual_name or "default", "id": None, "type": "Manual Entry"}

    # Determine default choice index
    default_idx = 1
    matched_idx = None
    if current_input:
        for idx, dev in enumerate(audio_inputs, 1):
            if current_input.lower() == dev["name"].lower() or current_input.lower() in dev["name"].lower():
                matched_idx = idx
                break

    if matched_idx is not None:
        default_idx = matched_idx
    else:
        for idx, dev in enumerate(audio_inputs, 1):
            if dev.get("default"):
                default_idx = idx
                break

    if RICH_AVAILABLE:
        table = Table(title="Detected Audio Input Devices (Microphones)", show_header=True, header_style="bold green")
        table.add_column("#", style="dim", width=4)
        table.add_column("Device Name", style="bold white")
        table.add_column("Type", style="cyan")
        table.add_column("Source ID", style="dim", justify="center")
        table.add_column("Status", justify="center")

        for idx, dev in enumerate(audio_inputs, 1):
            is_cur = False
            if current_input and (current_input.lower() == dev["name"].lower() or current_input.lower() in dev["name"].lower()):
                is_cur = True

            status_parts = []
            if dev.get("default"):
                status_parts.append("[green]Default[/green]")
            if is_cur:
                status_parts.append("[bold magenta][CURRENT][/bold magenta]")
            if not status_parts:
                status_parts.append("[dim]Available[/dim]")

            status_str = " ".join(status_parts)
            table.add_row(str(idx), dev["name"], dev.get("type", "Audio Source"), str(dev.get("id", "N/A")), status_str)

        ui.console.print(table)
    else:
        print("\nDetected Audio Input Devices (Microphones):")
        for idx, dev in enumerate(audio_inputs, 1):
            is_cur = " [CURRENT]" if current_input and (current_input.lower() in dev["name"].lower() or dev["name"].lower() in current_input.lower()) else ""
            is_def = " (Default)" if dev.get("default") else ""
            print(f" [{idx}] {dev['name']} [{dev.get('type', 'Mic')}]{is_def}{is_cur}")

    print("\nOptions:")
    num_devices = len(audio_inputs)
    print(f" [1-{num_devices}] Select a microphone device from the list")
    if selected_bt and selected_bt.get("name") and selected_bt.get("name") != "None":
        print(f" [b] Use selected Bluetooth device microphone ({selected_bt['name']})")
    print(" [0] Use system default microphone (default)")
    print(" [m] Enter microphone name manually")

    prompt_str = f"Choose audio input option (default: {default_idx}): "

    while True:
        try:
            choice = input(prompt_str).strip().lower()
            if not choice:
                return audio_inputs[default_idx - 1]

            if choice.isdigit():
                val = int(choice)
                if 1 <= val <= num_devices:
                    return audio_inputs[val - 1]
                elif val == 0:
                    return {"name": "default", "id": None, "type": "System Default"}
            elif choice == "b" and selected_bt and selected_bt.get("name") and selected_bt.get("name") != "None":
                return {"name": selected_bt["name"], "id": None, "type": "Bluetooth Mic"}
            elif choice in ("0", "default", "none"):
                return {"name": "default", "id": None, "type": "System Default"}
            elif choice == "m":
                manual = input("Enter microphone device name (e.g. Wireless Microphone): ").strip()
                return {"name": manual or "default", "id": None, "type": "Manual Entry"}

            ui.print_warning(f"Invalid option '{choice}'.")
        except (KeyboardInterrupt, EOFError):
            print()
            ui.print_info("Selection cancelled by user.")
            sys.exit(0)


def review_and_apply(
    env_path: Path,
    selected_camera: Optional[Dict[str, Any]],
    selected_bt: Optional[Dict[str, Any]],
    selected_audio_in: Optional[Dict[str, Any]],
    pulse_socket: str,
    dry_run: bool = False,
    auto_yes: bool = False
) -> bool:
    """
    Display a review summary of target configuration and write changes to .env.

    Calculates changes for CAMERA_DEVICE, CAMERA_NAME, BLUETOOTH_AUDIO_NAME,
    BLUETOOTH_AUDIO_MAC, AUDIO_OUTPUT_DEVICE, AUDIO_INPUT_DEVICE, PULSE_SERVER,
    and PULSE_SOCKET. Prompts the user for confirmation (or auto-applies if
    auto_yes is True) and invokes `update_env_file()`. Also sets runtime
    defaults via PipeWire `wpctl`.

    Args:
        env_path (Path): Path to .env file to update.
        selected_camera (Optional[Dict[str, Any]]): Selected camera dict.
        selected_bt (Optional[Dict[str, Any]]): Selected Bluetooth device dict.
        selected_audio_in (Optional[Dict[str, Any]]): Selected microphone dict.
        pulse_socket (str): Filesystem path to host native PulseAudio socket.
        dry_run (bool): If True, previews changes without writing to disk. Defaults to False.
        auto_yes (bool): If True, skips confirmation prompt and applies immediately. Defaults to False.

    Returns:
        bool: True if configuration was applied successfully; False if cancelled or failed.

    Example:
        >>> ok = review_and_apply(Path(".env"), cam, bt, mic, "/run/user/1000/pulse/native")
    """
    ui.print_section("Configuration Summary")

    updates = {}
    if selected_camera:
        updates["CAMERA_DEVICE"] = selected_camera["path"]
        updates["CAMERA_NAME"] = selected_camera.get("name", "Webcam")

    if selected_bt:
        updates["BLUETOOTH_AUDIO_NAME"] = selected_bt["name"]
        updates["BLUETOOTH_AUDIO_MAC"] = selected_bt["mac"]
        updates["AUDIO_OUTPUT_DEVICE"] = selected_bt["name"]
        updates["PULSE_SERVER"] = "unix:/tmp/pulse-socket"
        if pulse_socket and os.path.exists(pulse_socket):
            updates["PULSE_SOCKET"] = pulse_socket
    else:
        # User selected no bluetooth
        updates["BLUETOOTH_AUDIO_NAME"] = "None"
        updates["BLUETOOTH_AUDIO_MAC"] = ""
        updates["AUDIO_OUTPUT_DEVICE"] = "default"
        if pulse_socket and os.path.exists(pulse_socket):
            updates["PULSE_SOCKET"] = pulse_socket
            updates["PULSE_SERVER"] = "unix:/tmp/pulse-socket"

    if selected_audio_in:
        updates["AUDIO_INPUT_DEVICE"] = selected_audio_in["name"]
    else:
        updates["AUDIO_INPUT_DEVICE"] = "default"

    if RICH_AVAILABLE:
        table = Table(title=f"Target Configuration ({env_path.name})", show_header=True, header_style="bold green")
        table.add_column("Environment Variable", style="cyan")
        table.add_column("Assigned Value", style="bold white")
        for k, v in updates.items():
            table.add_row(k, v)
        ui.console.print(table)
    else:
        print(f"\nTarget Configuration for {env_path.name}:")
        for k, v in updates.items():
            print(f"  {k}={v}")

    if dry_run:
        ui.print_info("Dry-run requested. No changes written to disk.")
        return True

    print()
    if not auto_yes:
        try:
            confirm = input(f"Write these settings to {env_path}? [Y/n]: ").strip().lower()
            if confirm in ("n", "no"):
                ui.print_warning("Update cancelled by user.")
                return False
        except (KeyboardInterrupt, EOFError):
            print()
            ui.print_info("Operation cancelled.")
            return False

    success = update_env_file(env_path, updates)
    if success:
        # Set default PipeWire source if an id is associated
        if selected_audio_in and selected_audio_in.get("id"):
            set_default_pipewire_source(selected_audio_in["id"])
        if selected_bt and selected_bt.get("name") and selected_bt["name"] != "None":
            set_default_bluetooth_sink(selected_bt["name"])

        ui.print_success(f"Successfully updated configuration in: [bold]{env_path}[/bold]")
        print("\nNext steps to run Halloween Doorcam:")
        print("  1. Recreate containers with new devices:")
        print("     docker compose up -d --build")
        print("  2. View live logs to verify video & speech recognition:")
        print("     docker compose logs -f doorcam")
        print()
    return success


def main() -> None:
    """
    Main entry point for the device configuration wizard CLI.

    Supports both interactive step-by-step terminal navigation and non-interactive
    automation flags (e.g. `--camera`, `--bt-mac`, `--audio-input`, `--yes`).
    Detects hardware, reads `.env`, displays interactive menus or resolves CLI
    arguments, and executes `review_and_apply`.

    CLI Options:
      --env-file <path>: Path to .env file (default: .env).
      --list, -l: Enumerate webcams, Bluetooth devices, and microphones and exit.
      --json: Dump all discovered device metadata in structured JSON.
      --camera <path>: Explicit webcam device path (e.g. /dev/video0).
      --bt-mac <mac>: Bluetooth device MAC address.
      --audio-input, --mic <name>: Microphone device name or ID.
      --no-bluetooth: Explicitly configure for wired/default system audio.
      --connect: Attempt Bluetooth connection if currently disconnected.
      --scan: Run discovery scan before showing menu.
      --dry-run: Simulate updates without modifying disk.
      --yes, -y: Skip interactive confirmation prompt.

    Returns:
        None
    """
    parser = argparse.ArgumentParser(
        description="🎃 Halloween Doorcam - Device Setup & Configuration Wizard",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--env-file", type=str, default=".env", help="Path to the .env file (default: .env in current dir)")
    parser.add_argument("--list", "-l", action="store_true", help="List detected webcams, audio devices and microphones then exit")
    parser.add_argument("--json", action="store_true", help="Output detected devices in JSON format")
    parser.add_argument("--camera", type=str, help="Set CAMERA_DEVICE path directly without interactive prompt")
    parser.add_argument("--bt-mac", type=str, help="Set Bluetooth device by MAC address directly")
    parser.add_argument("--audio-input", "--mic", type=str, help="Set AUDIO_INPUT_DEVICE directly without interactive prompt")
    parser.add_argument("--no-bluetooth", action="store_true", help="Explicitly configure system without Bluetooth audio")
    parser.add_argument("--connect", action="store_true", help="Attempt to connect the selected Bluetooth device if disconnected")
    parser.add_argument("--scan", action="store_true", help="Scan for nearby Bluetooth devices before presenting menu")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without modifying the .env file")
    parser.add_argument("--yes", "-y", action="store_true", help="Automatically accept and apply configuration")
    
    args = parser.parse_args()

    # Determine paths
    script_dir = Path(__file__).resolve().parent
    env_path = Path(args.env_file)
    if not env_path.is_absolute():
        env_path = script_dir / env_path

    # Read current configuration
    current_env = read_env_file(env_path)
    current_camera = current_env.get("CAMERA_DEVICE", "/dev/video2")
    current_bt_mac = current_env.get("BLUETOOTH_AUDIO_MAC", "")
    current_audio_in = current_env.get("AUDIO_INPUT_DEVICE", "")

    # Locate PulseAudio / PipeWire socket
    user_runtime = os.getenv("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    pulse_socket = os.path.join(user_runtime, "pulse", "native")

    # Detect devices
    if args.scan:
        scan_bluetooth_devices(8)

    webcams = detect_webcams()
    bt_devices = get_bluetooth_audio_devices()
    audio_inputs = detect_audio_input_devices()

    # Handle JSON output
    if args.json:
        data = {
            "webcams": webcams,
            "bluetooth_audio": bt_devices,
            "audio_inputs": audio_inputs,
            "current_configuration": {
                "CAMERA_DEVICE": current_camera,
                "BLUETOOTH_AUDIO_MAC": current_bt_mac,
                "AUDIO_INPUT_DEVICE": current_audio_in,
                "PULSE_SOCKET": pulse_socket if os.path.exists(pulse_socket) else ""
            }
        }
        print(json.dumps(data, indent=2))
        return

    # Handle --list option
    if args.list:
        ui.print_banner()
        ui.print_section("Detected Webcams")
        for idx, cam in enumerate(webcams, 1):
            is_cur = " [CURRENT]" if cam["path"] == current_camera else ""
            print(f" [{idx}] {cam['path']} - {cam['name']}{is_cur}")
            if cam["formats"]:
                print(f"     Formats: {', '.join(cam['formats'])}")

        ui.print_section("Detected Bluetooth Audio Devices")
        for idx, dev in enumerate(bt_devices, 1):
            is_cur = " [CURRENT]" if dev["mac"].upper() == current_bt_mac.upper() else ""
            status = "Connected" if dev["connected"] else "Disconnected (Paired)"
            print(f" [{idx}] {dev['name']} ({dev['mac']}) - {status}{is_cur}")

        ui.print_section("Detected Audio Input Devices (Microphones)")
        for idx, dev in enumerate(audio_inputs, 1):
            is_cur = " [CURRENT]" if current_audio_in and (current_audio_in.lower() in dev["name"].lower() or dev["name"].lower() in current_audio_in.lower()) else ""
            def_tag = " (Default)" if dev.get("default") else ""
            id_str = f" (ID: {dev['id']})" if dev.get("id") else ""
            print(f" [{idx}] {dev['name']} [{dev.get('type', 'Audio In')}]{id_str}{def_tag}{is_cur}")
        return

    # Non-interactive CLI configuration
    if args.camera or args.bt_mac or args.no_bluetooth or args.audio_input:
        selected_camera = None
        if args.camera:
            matching = [c for c in webcams if c["path"] == args.camera]
            selected_camera = matching[0] if matching else {"path": args.camera, "name": "Custom Webcam"}
        else:
            selected_camera = {"path": current_camera, "name": current_env.get("CAMERA_NAME", "Webcam")}

        selected_bt = None
        if args.bt_mac:
            matching = [b for b in bt_devices if b["mac"].upper() == args.bt_mac.upper()]
            selected_bt = matching[0] if matching else {"mac": args.bt_mac, "name": "Bluetooth Device", "connected": False}
            if args.connect and not selected_bt.get("connected"):
                ui.print_info(f"Attempting to connect to {selected_bt['mac']}...")
                ok, msg = connect_bluetooth_device(selected_bt["mac"])
                if ok:
                    ui.print_success(msg)
                else:
                    ui.print_warning(msg)
        elif args.no_bluetooth:
            selected_bt = None
        elif current_bt_mac:
            matching = [b for b in bt_devices if b["mac"].upper() == current_bt_mac.upper()]
            selected_bt = matching[0] if matching else {"mac": current_bt_mac, "name": current_env.get("BLUETOOTH_AUDIO_NAME", "Bluetooth Device")}

        selected_audio_in = None
        if args.audio_input:
            matching_in = [a for a in audio_inputs if args.audio_input.lower() in a["name"].lower() or args.audio_input == a.get("id")]
            selected_audio_in = matching_in[0] if matching_in else {"name": args.audio_input, "id": None, "type": "Custom"}
        elif current_audio_in:
            matching_in = [a for a in audio_inputs if current_audio_in.lower() in a["name"].lower() or a["name"].lower() in current_audio_in.lower()]
            selected_audio_in = matching_in[0] if matching_in else {"name": current_audio_in, "id": None, "type": "Configured"}

        review_and_apply(env_path, selected_camera, selected_bt, selected_audio_in, pulse_socket, dry_run=args.dry_run, auto_yes=args.yes)
        return

    # Interactive Wizard Mode
    ui.print_banner()

    # 1. Select Webcam
    selected_camera = display_webcam_menu(webcams, current_camera)

    # 2. Select Bluetooth Audio Device
    selected_bt = None
    while True:
        selected_bt, should_rescan = display_bluetooth_menu(bt_devices, current_bt_mac)
        if should_rescan:
            scan_bluetooth_devices(8)
            bt_devices = get_bluetooth_audio_devices()
            continue
        break

    # 3. If selected Bluetooth device is disconnected, offer to connect
    if selected_bt and not selected_bt.get("connected"):
        ui.print_section("Bluetooth Device Connection")
        print(f"'{selected_bt['name']}' ({selected_bt['mac']}) is currently disconnected.")
        try:
            connect_choice = input("Would you like to connect to this device now? [Y/n]: ").strip().lower()
            if connect_choice not in ("n", "no"):
                ui.print_info(f"Connecting to {selected_bt['name']} ({selected_bt['mac']})...")
                ok, msg = connect_bluetooth_device(selected_bt["mac"], timeout=10)
                if ok:
                    ui.print_success(f"Connected to {selected_bt['name']}!")
                    selected_bt["connected"] = True
                else:
                    ui.print_warning(f"Could not connect: {msg}")
                    ui.print_info("The device will still be configured in .env and will connect automatically when turned on.")
        except (KeyboardInterrupt, EOFError):
            print()

    # 4. Select Audio Input Device (Microphone)
    selected_audio_in = display_audio_input_menu(audio_inputs, current_audio_in, selected_bt)

    # 5. Review and Apply
    review_and_apply(env_path, selected_camera, selected_bt, selected_audio_in, pulse_socket, dry_run=args.dry_run, auto_yes=args.yes)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAborted by user.")
        sys.exit(0)
