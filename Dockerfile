# Isolated runtime: model-written code runs inside this container, not on your machine.
# ffmpeg is required for Muse Voice Transcribe (browser audio → mono 16 kHz WAV).
# git is required for cloning GitHub repositories via attach_repo.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8000"]
