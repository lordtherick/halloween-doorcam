# Halloween Doorcam Docker Container

A headless interactive Halloween gargoyle doorcam. When motion is detected via camera, the gargoyle asks a spooky riddle from `riddles.txt`, reads it aloud using `edge-tts` and `mpg123`, listens for the trick-or-treater's answer via microphone using OpenAI Whisper, and judges their answer. If correct, they earn a sweet; if wrong or silent, the gargoyle reveals the answer and lets them take a sweet anyway for wearing a scary costume!

---

## Prerequisites

1. **Docker & Docker Compose** installed.
2. **Local Ollama Server** running on your host machine:
   ```bash
   ollama run llama3
   ```
   > **Note on Host Ollama Access:**
   > By default, `docker-compose.yml` configures `extra_hosts: ["host.docker.internal:host-gateway"]` and `.env` sets `OLLAMA_HOST=http://host.docker.internal:11434`.
   > If running Docker on native Linux, ensure Ollama allows connections by setting `OLLAMA_HOST=0.0.0.0` on the host, or uncomment `network_mode: "host"` in `docker-compose.yml`.
3. **Camera & Audio Devices**:
   - Webcams accessible under `/dev/video*`.
   - Sound devices accessible via ALSA (`/dev/snd`) and PipeWire/PulseAudio (`/run/user/1000/pulse/native`).
   - Run the automated device setup tool:
     ```bash
     ./setup_devices.sh
     ```

---

## Device Setup Wizard (`setup_devices.sh` / `setup_devices.py`)

An interactive configuration tool that scans for connected webcams (V4L2 capture nodes), paired/connected Bluetooth audio devices (headsets/speakers), and audio input devices / microphones (USB wireless mics, webcam mics, built-in mics), lets you choose your desired devices, and safely writes the configuration into `.env`:

```bash
# Launch interactive wizard
./setup_devices.sh

# Or run directly with Python
./setup_devices.py

# List detected devices without modifying configuration
./setup_devices.py --list

# Non-interactive CLI configuration (webcam, bluetooth speaker, and wireless mic)
./setup_devices.py --camera /dev/video0 --bt-mac 4C:3C:8F:93:76:CE --audio-input "Wireless Microphone" --yes
```

---

## Voice & Sound Tester (`test_voice.sh` / `test_voice.py`)

Preview, tune, and audition TTS voices, pitch, and speed adjustments before running the doorcam container:

```bash
# Launch interactive voice review & tuning menu
./test_voice.sh

# Audition the current voice with a custom phrase
./test_voice.sh --text "Welcome foolish mortal! What is your answer?"

# Audition spooky voice presets (e.g. deep phantom, crypt keeper, gothic witch)
./test_voice.sh --preset deep_phantom_us

# Test a custom voice and pitch, and immediately save it to .env
./test_voice.sh --voice en-US-ChristopherNeural --pitch -22Hz --rate -15% --save
```

---

## Spooky Sound Effects & AudioCraft (`generate_fx.sh` / `generate_fx.py`)

Pre-generate, preview, and audition cinematic Halloween sound effects, stingers, and ambient audio (crypt gate grinding on motion, gothic cathedral riddle bells, magical victory chimes, and dungeon gong failures) using Meta's **AudioCraft** (AudioGen) or the built-in instant procedural sound engine:

```bash
# List all sound effects and their caching status
./generate_fx.sh --list

# Pre-generate and cache all sound effects (0ms interaction latency)
./generate_fx.sh --generate-all

# Audition a sound effect through your speaker
./generate_fx.sh --play motion_detected
./generate_fx.sh --play correct_answer
./generate_fx.sh --play wrong_answer

# Generate a custom sound effect using an AudioCraft text prompt
./generate_fx.sh --prompt "spooky witch laughing with thunder" --name witch_laugh
```

---

## Configuration (`.env`)

The `.env` file covers all major settings:

| Environment Variable | Default Value | Description |
|---|---|---|
| `CAMERA_DEVICE` | `/dev/video2` | Video capture device path (e.g. `/dev/video0` or `/dev/video2`) |
| `CAMERA_NAME` | *(Auto-detected)* | Friendly name of selected webcam |
| `BLUETOOTH_AUDIO_NAME` | *(Selected device)*| Name of selected Bluetooth audio headset/speaker |
| `BLUETOOTH_AUDIO_MAC` | *(Selected MAC)* | Bluetooth MAC address (e.g. `E8:EE:CC:6F:DF:C3`) |
| `AUDIO_OUTPUT_DEVICE` | `default` | Audio output sink / speaker device name |
| `AUDIO_INPUT_DEVICE` | `default` | Audio input source / microphone device name |
| `PULSE_SERVER` | `unix:/tmp/pulse-socket` | PulseAudio socket endpoint inside container |
| `PULSE_SOCKET` | `/run/user/1000/pulse/native` | Host PulseAudio/PipeWire native socket path |
| `OLLAMA_HOST` | `http://host.docker.internal:11434` | URL to host's Ollama instance |
| `OLLAMA_MODEL` | `llama3.2` | LLM model used for riddles and evaluation |
| `WHISPER_MODEL` | `base` | Whisper speech-to-text model |
| `TTS_VOICE` | `en-GB-RyanNeural` | Microsoft Edge TTS voice |
| `TTS_RATE` | `-10%` | Voice speed adjustment |
| `TTS_PITCH` | `-15Hz` | Voice pitch adjustment |
| `MOTION_THRESHOLD` | `5000` | Contour area threshold for motion trigger |
| `MOTION_COOLDOWN` | `15` | Cooldown period (in seconds) between triggers |
| `AMBIENT_NOISE_DURATION` | `1.5` | Ambient noise sampling duration (seconds) |
| `LISTEN_TIMEOUT` | `6` | Silence timeout before giving up on speech |
| `LISTEN_PHRASE_TIME_LIMIT`| `10` | Maximum recording length for answers |
| `RIDDLES_FILE` | `riddles.txt` | Path to text file containing Halloween riddles and answers |
| `CORRECT_ANSWER_MESSAGE` | *(Sweet reward)* | Message spoken when child solves the riddle |
| `WRONG_ANSWER_MESSAGE` | *(Costume reward)* | Message revealing answer and granting sweet for scary costume |
| `SILENT_ANSWER_MESSAGE` | *(Costume reward)* | Message when silent revealing answer and granting sweet |

---

## Usage

### 1. Build and Run Container
```bash
docker compose up -d --build
```

### 2. View Live Container Logs
```bash
docker compose logs -f
```

### 3. Stop Container
```bash
docker compose down
```
