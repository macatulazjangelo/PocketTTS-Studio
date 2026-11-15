# Pocket TTS Studio

A local web interface for Pocket TTS, with a FastAPI backend and a plain HTML, CSS, and JavaScript frontend.

## Features

- Generate speech and play or download WAV recordings.
- Browse voices, rename them, and mark favorites.
- Browse and install community voices from Kyutai’s Hugging Face voice collection.
- Split long scripts into chunks, track progress, resume interrupted jobs, and merge completed audio.
- Keep voice settings, recording counters, and long-form job metadata locally.

## Run on macOS

The existing development environment uses Python 3.13. Run these commands from the project root:

```sh
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 in your browser. Stop the server with Control-C.

The dependency versions match the original local environment. Model and voice assets may be downloaded on first use, so an internet connection and sufficient disk space are needed. Follow any upstream model access requirements if prompted. Available voices depend on the installed Pocket TTS version.

## Project layout

- `backend/main.py`: web server, speech generation, community voices, and long-form jobs.
- `backend/voice_library.py`: SQLite voice library and recording counters.
- `backend/text_chunker.py`: text splitting for long-form generation.
- `frontend/`: browser interface served by FastAPI.
- `data/`: automatically created local database, voices, recordings, scripts, and job manifests; excluded from Git.

## Local data and privacy

This repository contains application source only. Virtual environments, secrets, generated audio, databases, downloaded voices, model weights, caches, and historical backup files are excluded by `.gitignore`. Keep credentials outside source code. Back up `data/` separately if you need to preserve recordings and settings.

The server is intended for use on your own computer and has no authentication. Keep the default loopback binding for local use.

## Credits

Speech synthesis is provided by Kyutai’s Pocket TTS. Community voice assets are obtained from the `kyutai/tts-voices` Hugging Face repository at runtime. Upstream software, models, and voice assets retain their own terms and licenses.
