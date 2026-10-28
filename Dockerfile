FROM python:3.11-slim-bookworm

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive

# Install system dependencies required for OpenCV, audio (ALSA, PortAudio, mpg123), and Whisper (ffmpeg)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    mpg123 \
    alsa-utils \
    libasound2-plugins \
    portaudio19-dev \
    v4l-utils \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-cache the default Whisper model into the container image
ARG DEFAULT_WHISPER_MODEL=base
RUN python3 -c "import whisper; whisper.load_model('${DEFAULT_WHISPER_MODEL}')"

# Copy application source code and riddles
COPY doorcam.py spooky_fx.py generate_fx.py riddles.txt ./

CMD ["python3", "doorcam.py"]
