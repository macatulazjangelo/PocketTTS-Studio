from pathlib import Path
from uuid import uuid4
from threading import Lock, Thread

import numpy as np
import json
from urllib.parse import quote
from urllib.request import urlopen
from backend.text_chunker import chunk_text

import scipy.io.wavfile
import hashlib
import shutil
from urllib.request import Request, urlopen
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pocket_tts import TTSModel
from urllib.parse import quote

from contextlib import asynccontextmanager
from backend.voice_library import (
    initialize_database,
    get_voices,
    get_voice,
    update_voice,
    add_voice,
    get_next_recording_number,
)

longform_jobs = {}
longform_jobs_lock = Lock()

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
COMMUNITY_VOICE_DIR = (
    BASE_DIR / "data" / "voices" / "community"
)

COMMUNITY_VOICE_DIR.mkdir(
    parents=True,
    exist_ok=True
)
RECORDINGS_DIR = BASE_DIR / "data" / "recordings"

RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

def run_longform_job(
    job_id,
    text,
    voice_id
):
    selected_voice = get_voice(voice_id)

    try:
        chunks = chunk_text(text)

        job_dir = LONGFORM_DIR / job_id

        with longform_jobs_lock:
            completed_chunks = (
                longform_jobs[job_id]
                .get("completed_chunks", 0)
            )

            longform_jobs[job_id][
                "status"
            ] = "generating"

            longform_jobs[job_id][
                "total_chunks"
            ] = len(chunks)

            longform_jobs[job_id][
                "error"
            ] = None

        save_job_manifest(job_id)

        with generation_lock:

            tts = get_model()

            if voice_id not in voice_cache:
                voice_cache[voice_id] = (
                    tts.get_state_for_audio_prompt(
                        selected_voice["source"]
                    )
                )

            voice_state = voice_cache[voice_id]

            for index, chunk in enumerate(
                chunks,
                start=1
            ):

                # Already successfully generated.
                if index <= completed_chunks:

                    existing_file = (
                        job_dir
                        / f"chunk_{index:03d}.wav"
                    )

                    if existing_file.is_file():
                        print(
                            f"[Long-form {job_id[:8]}] "
                            f"Skipping completed chunk "
                            f"{index}/{len(chunks)}"
                        )

                        continue

                    # Manifest says the chunk exists,
                    # but the WAV is missing.
                    # Resume from this point instead.
                    completed_chunks = index - 1

                    with longform_jobs_lock:
                        longform_jobs[job_id][
                            "completed_chunks"
                        ] = completed_chunks

                    save_job_manifest(job_id)

                print(
                    f"[Long-form {job_id[:8]}] "
                    f"Generating chunk "
                    f"{index}/{len(chunks)}..."
                )

                with longform_jobs_lock:
                    longform_jobs[job_id][
                        "current_chunk"
                    ] = index

                save_job_manifest(job_id)

                audio = tts.generate_audio(
                    voice_state,
                    chunk
                )

                filename = (
                    f"chunk_{index:03d}.wav"
                )

                output_path = (
                    job_dir / filename
                )

                scipy.io.wavfile.write(
                    output_path,
                    tts.sample_rate,
                    audio.detach()
                        .cpu()
                        .numpy()
                )

                completed_chunks = index

                with longform_jobs_lock:
                    longform_jobs[job_id][
                        "completed_chunks"
                    ] = index

                save_job_manifest(job_id)

        with longform_jobs_lock:
            longform_jobs[job_id][
                "status"
            ] = "completed"

            longform_jobs[job_id][
                "current_chunk"
            ] = None

        save_job_manifest(job_id)

        print(
            f"[Long-form {job_id[:8]}] "
            "Generation completed."
        )

    except Exception as error:

        print(
            f"[Long-form {job_id[:8]}] "
            f"FAILED: {error}"
        )

        with longform_jobs_lock:
            longform_jobs[job_id][
                "status"
            ] = "failed"

            longform_jobs[job_id][
                "error"
            ] = str(error)

            longform_jobs[job_id][
                "current_chunk"
            ] = None

        save_job_manifest(job_id)

LONGFORM_DIR = BASE_DIR / "data" / "longform"

LONGFORM_DIR.mkdir(
    parents=True,
    exist_ok=True
)

def get_job_manifest_path(job_id: str):
    return (
        LONGFORM_DIR
        / job_id
        / "manifest.json"
    )


def save_job_manifest(job_id: str):
    """
    Save the current in-memory job state to disk.
    """

    with longform_jobs_lock:
        job = longform_jobs.get(job_id)

        if job is None:
            return

        snapshot = dict(job)

    manifest_path = get_job_manifest_path(
        job_id
    )

    manifest_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    temporary_path = (
        manifest_path.with_suffix(".json.tmp")
    )

    with temporary_path.open(
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            snapshot,
            file,
            indent=2
        )

    temporary_path.replace(
        manifest_path
    )


def load_job_manifests():
    """
    Restore long-form job metadata after
    the server restarts.
    """

    if not LONGFORM_DIR.exists():
        return

    for job_dir in LONGFORM_DIR.iterdir():

        if not job_dir.is_dir():
            continue

        manifest_path = (
            job_dir / "manifest.json"
        )

        if not manifest_path.is_file():
            continue

        try:
            with manifest_path.open(
                "r",
                encoding="utf-8"
            ) as file:
                job = json.load(file)

            job_id = job.get("job_id")

            if not job_id:
                continue

            # A job cannot still be actively
            # generating after this server
            # process has restarted.
            if job.get("status") in {
                "queued",
                "generating"
            }:
                job["status"] = "interrupted"
                job["current_chunk"] = None

            with longform_jobs_lock:
                longform_jobs[job_id] = job

            # Persist any interrupted-state
            # correction we just made.
            if job.get("status") == "interrupted":
                save_job_manifest(job_id)

            print(
                f"[Long-form] Restored job "
                f"{job_id[:8]} "
                f"({job['status']})"
            )

        except Exception as error:
            print(
                "[Long-form] Could not restore "
                f"{job_dir.name}: {error}"
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()

    load_job_manifests()

    yield


app = FastAPI(
    title="Pocket TTS Studio",
    lifespan=lifespan
)

app.mount(
    "/static",
    StaticFiles(directory=FRONTEND_DIR),
    name="static"
)

# Built-in Pocket TTS voices
VOICES = {
    "alba": "alba",
    "marius": "marius",
    "jean": "jean",
}

model = None
voice_cache = {}
generation_lock = Lock()

longform_jobs = {}
longform_jobs_lock = Lock()


class GenerationRequest(BaseModel):
    text: str = Field(min_length=1, max_length=3000)
    voice: str = "alba"

class LongFormRequest(BaseModel):
    text: str = Field(min_length=1)
    voice: str = "alba"


def get_model():
    global model

    if model is None:
        model = TTSModel.load_model()

    return model

def run_longform_job(
    job_id,
    text,
    voice_id
):
    selected_voice = get_voice(voice_id)

    try:
        chunks = chunk_text(text)

        job_dir = LONGFORM_DIR / job_id

        with longform_jobs_lock:
            completed_chunks = (
                longform_jobs[job_id]
                .get("completed_chunks", 0)
            )

            longform_jobs[job_id][
                "status"
            ] = "generating"

            longform_jobs[job_id][
                "total_chunks"
            ] = len(chunks)

            longform_jobs[job_id][
                "error"
            ] = None

        save_job_manifest(job_id)

        with generation_lock:

            tts = get_model()

            if voice_id not in voice_cache:
                voice_cache[voice_id] = (
                    tts.get_state_for_audio_prompt(
                        selected_voice["source"]
                    )
                )

            voice_state = voice_cache[voice_id]

            for index, chunk in enumerate(
                chunks,
                start=1
            ):

                # Already successfully generated.
                if index <= completed_chunks:

                    existing_file = (
                        job_dir
                        / f"chunk_{index:03d}.wav"
                    )

                    if existing_file.is_file():
                        print(
                            f"[Long-form {job_id[:8]}] "
                            f"Skipping completed chunk "
                            f"{index}/{len(chunks)}"
                        )

                        continue

                    # Manifest says the chunk exists,
                    # but the WAV is missing.
                    # Resume from this point instead.
                    completed_chunks = index - 1

                    with longform_jobs_lock:
                        longform_jobs[job_id][
                            "completed_chunks"
                        ] = completed_chunks

                    save_job_manifest(job_id)

                print(
                    f"[Long-form {job_id[:8]}] "
                    f"Generating chunk "
                    f"{index}/{len(chunks)}..."
                )

                with longform_jobs_lock:
                    longform_jobs[job_id][
                        "current_chunk"
                    ] = index

                save_job_manifest(job_id)

                audio = tts.generate_audio(
                    voice_state,
                    chunk
                )

                filename = (
                    f"chunk_{index:03d}.wav"
                )

                output_path = (
                    job_dir / filename
                )

                scipy.io.wavfile.write(
                    output_path,
                    tts.sample_rate,
                    audio.detach()
                        .cpu()
                        .numpy()
                )

                completed_chunks = index

                with longform_jobs_lock:
                    longform_jobs[job_id][
                        "completed_chunks"
                    ] = index

                save_job_manifest(job_id)

        with longform_jobs_lock:
            longform_jobs[job_id][
                "status"
            ] = "completed"

            longform_jobs[job_id][
                "current_chunk"
            ] = None

        save_job_manifest(job_id)

        print(
            f"[Long-form {job_id[:8]}] "
            "Generation completed."
        )

    except Exception as error:

        print(
            f"[Long-form {job_id[:8]}] "
            f"FAILED: {error}"
        )

        with longform_jobs_lock:
            longform_jobs[job_id][
                "status"
            ] = "failed"

            longform_jobs[job_id][
                "error"
            ] = str(error)

            longform_jobs[job_id][
                "current_chunk"
            ] = None

        save_job_manifest(job_id)

def merge_longform_chunks(job_id: str):
    job_dir = LONGFORM_DIR / job_id

    with longform_jobs_lock:
        job = longform_jobs.get(job_id)

        if job is None:
            raise ValueError(
                "Long-form job not found."
            )

        total_chunks = job["total_chunks"]

    if total_chunks <= 0:
        raise ValueError(
            "Job contains no audio chunks."
        )

    audio_parts = []
    expected_sample_rate = None

    for index in range(
        1,
        total_chunks + 1
    ):
        chunk_path = (
            job_dir
            / f"chunk_{index:03d}.wav"
        )

        if not chunk_path.is_file():
            raise ValueError(
                f"Missing chunk {index}."
            )

        sample_rate, audio = (
            scipy.io.wavfile.read(
                chunk_path
            )
        )

        if expected_sample_rate is None:
            expected_sample_rate = (
                sample_rate
            )

        elif sample_rate != expected_sample_rate:
            raise ValueError(
                "Audio chunks have "
                "different sample rates."
            )

        audio_parts.append(audio)

    if not audio_parts:
        raise ValueError(
            "No audio was available to merge."
        )

    merged_audio = np.concatenate(
        audio_parts,
        axis=0
    )

    output_path = (
        job_dir / "final.wav"
    )

    scipy.io.wavfile.write(
        output_path,
        expected_sample_rate,
        merged_audio
    )

    return output_path

@app.post(
    "/api/longform/{job_id}/merge"
)
def merge_longform_job(
    job_id: str
):
    with longform_jobs_lock:
        job = longform_jobs.get(job_id)

        if job is None:
            raise HTTPException(
                status_code=404,
                detail="Long-form job not found."
            )

        if job["status"] != "completed":
            raise HTTPException(
                status_code=409,
                detail=(
                    "Generation must be completed "
                    "before merging."
                )
            )

        voice_name = job["voice_name"]

    try:
        output_path = (
            merge_longform_chunks(job_id)
        )

        recording_number = (
            get_next_recording_number(
                job["voice"]
            )
        )

        display_name = (
            f"{voice_name}_"
            f"{recording_number:03d}"
        )

        with longform_jobs_lock:
            longform_jobs[job_id][
                "final_file"
            ] = output_path.name

            longform_jobs[job_id][
                "display_name"
            ] = display_name

        save_job_manifest(job_id)

        return {
            "success": True,
            "job_id": job_id,
            "filename": output_path.name,
            "display_name": display_name,
            "audio_url": (
                f"/api/longform/"
                f"{job_id}/audio"
            )
        }

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error)
        )

@app.get(
    "/api/longform/{job_id}/audio"
)
def get_longform_audio(
    job_id: str,
    download_name: str | None = None
):
    job_dir = LONGFORM_DIR / job_id

    output_path = (
        job_dir / "final.wav"
    )

    if not output_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=(
                "Merged recording not found."
            )
        )

    if download_name:
        safe_name = "".join(
            character
            for character in download_name
            if character not in '<>:"/\\|?*'
            and ord(character) >= 32
        ).strip().rstrip(". ")

        if not safe_name:
            safe_name = "Recording"

        safe_name = safe_name[:150]

        if not safe_name.lower().endswith(
            ".wav"
        ):
            safe_name += ".wav"

    else:
        safe_name = "Recording.wav"

    return FileResponse(
        output_path,
        media_type="audio/wav",
        filename=safe_name
    )

@app.post("/api/longform/start")
def start_longform_job(
    request: LongFormRequest
):
    selected_voice = get_voice(
        request.voice
    )

    if selected_voice is None:
        raise HTTPException(
            status_code=400,
            detail="Invalid voice selected"
        )

    text = request.text.strip()

    if not text:
        raise HTTPException(
            status_code=400,
            detail="Please enter some text"
        )

    chunks = chunk_text(text)

    if not chunks:
        raise HTTPException(
            status_code=400,
            detail="No valid chunks were created."
        )

    job_id = uuid4().hex

    job_dir = LONGFORM_DIR / job_id

    job_dir.mkdir(
        parents=True,
        exist_ok=False
    )

    script_path = job_dir / "script.txt"

    script_path.write_text(
        text,
        encoding="utf-8"

    )
    

    with longform_jobs_lock:
        longform_jobs[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "voice": request.voice,
            "voice_name": selected_voice["name"],
            "total_chunks": len(chunks),
            "completed_chunks": 0,
            "current_chunk": None,
            "error": None
        }
    save_job_manifest(job_id)

    worker = Thread(
        target=run_longform_job,
        args=(
            job_id,
            text,
            request.voice
        ),
        daemon=True
    )

    worker.start()

    return longform_jobs[job_id]

@app.get("/api/longform/{job_id}/status")
def get_longform_status(
    job_id: str
):
    with longform_jobs_lock:

        job = longform_jobs.get(job_id)

        if job is None:
            raise HTTPException(
                status_code=404,
                detail="Long-form job not found."
            )

        return dict(job)

@app.post("/api/longform/{job_id}/resume")
def resume_longform_job(
    job_id: str
):
    with longform_jobs_lock:
        job = longform_jobs.get(job_id)

        if job is None:
            raise HTTPException(
                status_code=404,
                detail="Long-form job not found."
            )

        if job["status"] == "generating":
            raise HTTPException(
                status_code=409,
                detail="Job is already generating."
            )

        if job["status"] == "queued":
            raise HTTPException(
                status_code=409,
                detail="Job is already queued."
            )

        if job["status"] == "completed":
            raise HTTPException(
                status_code=409,
                detail="Job is already completed."
            )

        voice_id = job["voice"]

    job_dir = LONGFORM_DIR / job_id
    script_path = job_dir / "script.txt"

    if not script_path.is_file():
        raise HTTPException(
            status_code=400,
            detail=(
                "Original script is unavailable "
                "for this job."
            )
        )

    text = script_path.read_text(
        encoding="utf-8"
    )

    chunks = chunk_text(text)

    # Determine actual contiguous progress
    # from the WAV files on disk.
    completed = 0

    for index in range(
        1,
        len(chunks) + 1
    ):
        chunk_path = (
            job_dir
            / f"chunk_{index:03d}.wav"
        )

        if not chunk_path.is_file():
            break

        completed = index

    with longform_jobs_lock:
        longform_jobs[job_id][
            "completed_chunks"
        ] = completed

        longform_jobs[job_id][
            "total_chunks"
        ] = len(chunks)

        longform_jobs[job_id][
            "status"
        ] = "queued"

        longform_jobs[job_id][
            "current_chunk"
        ] = None

        longform_jobs[job_id][
            "error"
        ] = None

    save_job_manifest(job_id)

    worker = Thread(
        target=run_longform_job,
        args=(
            job_id,
            text,
            voice_id
        ),
        daemon=True
    )

    worker.start()

    with longform_jobs_lock:
        return dict(
            longform_jobs[job_id]
        )


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "app": "Pocket TTS Studio"
    }


@app.get("/api/voices")
def list_voices():
    return get_voices()

class VoiceUpdate(BaseModel):
    name: str | None = None
    favorite: bool | None = None


@app.patch("/api/voices/{voice_id}")
def edit_voice(voice_id: str, request: VoiceUpdate):

    try:
        voice = update_voice(
            voice_id,
            name=request.name,
            favorite=request.favorite
        )

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error)
        )

    if voice is None:
        raise HTTPException(
            status_code=404,
            detail="Voice not found"
        )

    return voice

@app.get("/api/community-voices")
def community_voices():
    """
    Discover audio samples in Kyutai's official tts-voices repository.
    """

    repository = "kyutai/tts-voices"

    try:
        api_url = (
            "https://huggingface.co/api/models/"
            f"{repository}/tree/main"
        )

        with urlopen(api_url, timeout=20) as response:
            root_items = json.load(response)

        voices = []

        # Repository root contains voice directories.
        for item in root_items:

            if item.get("type") != "directory":
                continue

            directory = item["path"]

            directory_url = (
                "https://huggingface.co/api/models/"
                f"{repository}/tree/main/"
                f"{quote(directory, safe='/')}"
            )

            try:
                with urlopen(
                    directory_url,
                    timeout=20
                ) as response:
                    files = json.load(response)

            except Exception as error:
                print(
                    f"Could not inspect {directory}: {error}"
                )
                continue

            for file in files:

                path = file.get("path", "")

                if not path.lower().endswith(
                    (".wav", ".mp3", ".flac")
                ):
                    continue

                filename = Path(path).name
                stem = Path(filename).stem

                voices.append({
                    "id": path,
                    "name": stem.replace(
                        "-", " "
                    ).replace(
                        "_", " "
                    ).title(),
                    "collection": directory,
                    "filename": filename,
                    "path": path,

                    "preview_url": (
                        "https://huggingface.co/"
                        f"{repository}/resolve/main/"
                        f"{quote(path, safe='/')}"
                    )
                })

        return {
            "repository": repository,
            "count": len(voices),
            "voices": voices
        }

    except Exception as error:

        print(
            f"Community voice discovery error: {error}"
        )

        raise HTTPException(
            status_code=502,
            detail=(
                "Could not retrieve the "
                "Kyutai voice repository."
            )
        )


class CommunityVoiceInstall(BaseModel):
    name: str
    path: str

class ChunkPreviewRequest(BaseModel):
    text: str = Field(min_length=1)

@app.post("/api/chunk-preview")
def preview_chunks(
    request: ChunkPreviewRequest
):
    chunks = chunk_text(request.text)

    return {
        "character_count": len(request.text),
        "word_count": len(
            request.text.split()
        ),
        "chunk_count": len(chunks),

        "chunks": [
            {
                "number": index,
                "characters": len(chunk),
                "words": len(chunk.split()),
                "text": chunk
            }
            for index, chunk
            in enumerate(chunks, start=1)
        ]
    }

@app.post("/api/generate-long")
def generate_long_form(
    request: LongFormRequest
):
    selected_voice = get_voice(
        request.voice
    )

    if selected_voice is None:
        raise HTTPException(
            status_code=400,
            detail="Invalid voice selected"
        )

    text = request.text.strip()

    if not text:
        raise HTTPException(
            status_code=400,
            detail="Please enter some text"
        )

    chunks = chunk_text(text)

    if not chunks:
        raise HTTPException(
            status_code=400,
            detail="No valid text chunks were created."
        )

    job_id = uuid4().hex

    job_dir = LONGFORM_DIR / job_id

    job_dir.mkdir(
        parents=True,
        exist_ok=False
    )

    completed = []

    try:

        with generation_lock:

            tts = get_model()

            if request.voice not in voice_cache:

                voice_cache[request.voice] = (
                    tts.get_state_for_audio_prompt(
                        selected_voice["source"]
                    )
                )

            voice_state = (
                voice_cache[request.voice]
            )


            for index, chunk in enumerate(
                chunks,
                start=1
            ):

                print(
                    f"[Long-form {job_id[:8]}] "
                    f"Generating chunk "
                    f"{index}/{len(chunks)}..."
                )

                audio = tts.generate_audio(
                    voice_state,
                    chunk
                )

                filename = (
                    f"chunk_{index:03d}.wav"
                )

                output_path = (
                    job_dir / filename
                )

                scipy.io.wavfile.write(
                    output_path,
                    tts.sample_rate,
                    audio.detach()
                        .cpu()
                        .numpy()
                )

                completed.append({
                    "number": index,
                    "filename": filename,
                    "characters": len(chunk),
                    "words": len(
                        chunk.split()
                    )
                })


        return {
            "success": True,
            "job_id": job_id,
            "voice": request.voice,
            "voice_name":
                selected_voice["name"],
            "total_chunks": len(chunks),
            "completed_chunks":
                len(completed),
            "chunks": completed
        }


    except Exception as error:

        print(
            f"Long-form generation error: "
            f"{error}"
        )

        raise HTTPException(
            status_code=500,
            detail={
                "message": str(error),
                "job_id": job_id,
                "completed_chunks":
                    len(completed),
                "total_chunks":
                    len(chunks)
            }
        )

@app.post("/api/community-voices/install")
def install_community_voice(
    request: CommunityVoiceInstall
):

    repository = "kyutai/tts-voices"

    remote_path = request.path.strip()

    # Only allow supported audio files.
    if not remote_path.lower().endswith(
        (".wav", ".mp3", ".flac")
    ):
        raise HTTPException(
            status_code=400,
            detail="Unsupported voice file."
        )

    # Prevent paths such as ../../something
    path_parts = Path(remote_path).parts

    if (
        not remote_path
        or ".." in path_parts
        or remote_path.startswith("/")
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid voice path."
        )

    try:

        download_url = (
            "https://huggingface.co/"
            f"{repository}/resolve/main/"
            f"{quote(remote_path, safe='/')}"
        )

        # Stable unique ID for this repository file.
        digest = hashlib.sha256(
            remote_path.encode("utf-8")
        ).hexdigest()[:16]

        extension = (
            Path(remote_path).suffix.lower()
        )

        filename = (
            f"community_{digest}{extension}"
        )

        destination = (
            COMMUNITY_VOICE_DIR / filename
        )

        voice_id = (
            f"community_{digest}"
        )


        # Don't download it twice.
        existing = get_voice(voice_id)

        if existing:
            return {
                "success": True,
                "already_installed": True,
                "voice": existing
            }


        http_request = Request(
            download_url,
            headers={
                "User-Agent":
                    "Pocket-TTS-Studio/1.0"
            }
        )

        with urlopen(
            http_request,
            timeout=60
        ) as response:

            with open(
                destination,
                "wb"
            ) as output:

                shutil.copyfileobj(
                    response,
                    output
                )


        # Basic protection against an empty download.
        if (
            not destination.exists()
            or destination.stat().st_size == 0
        ):
            destination.unlink(
                missing_ok=True
            )

            raise RuntimeError(
                "Downloaded voice file is empty."
            )


        try:

            voice = add_voice(
                voice_id=voice_id,
                name=request.name.strip()
                    or Path(remote_path).stem,
                category="community",
                source=str(destination)
            )

        except Exception:

            # Don't leave an orphaned file if
            # database registration fails.
            destination.unlink(
                missing_ok=True
            )

            raise


        return {
            "success": True,
            "already_installed": False,
            "voice": voice
        }


    except HTTPException:
        raise

    except Exception as error:

        print(
            f"Community voice install error: "
            f"{error}"
        )

        raise HTTPException(
            status_code=500,
            detail=str(error)
        )

@app.post("/api/generate")
def generate(request: GenerationRequest):

    selected_voice = get_voice(request.voice)

    if selected_voice is None:
        raise HTTPException(
            status_code=400,
            detail="Invalid voice selected"
        )

    if not request.text.strip():
        raise HTTPException(
            status_code=400,
            detail="Please enter some text"
        )

    try:
        with generation_lock:

            tts = get_model()

            # Cache by voice ID
            if request.voice not in voice_cache:
                voice_cache[request.voice] = (
                    tts.get_state_for_audio_prompt(
                        selected_voice["source"]
                    )
                )

            voice_state = voice_cache[request.voice]

            audio = tts.generate_audio(
                voice_state,
                request.text
            )

            filename = f"{uuid4().hex}.wav"
            output_path = RECORDINGS_DIR / filename

            scipy.io.wavfile.write(
                output_path,
                tts.sample_rate,
                audio.detach().cpu().numpy()
            )

            recording_number = get_next_recording_number(
                request.voice
            )

            display_name = (
                f"{selected_voice['name']}_"
                f"{recording_number:03d}"
            )

        # IMPORTANT:
        # This return belongs to generate(), not another block/function.
        return {
            "success": True,
            "filename": filename,
            "display_name": display_name,
            "voice_name": selected_voice["name"],
            "recording_number": recording_number,
            "audio_url": f"/api/audio/{filename}"
        }

    except HTTPException:
        raise

    except Exception as error:
        print(f"Pocket TTS generation error: {error}")

        raise HTTPException(
            status_code=500,
            detail=str(error)
        )

@app.get("/api/audio/{filename}")
def get_audio(
    filename: str,
    download_name: str | None = None
):
    if (
        not filename.endswith(".wav")
        or Path(filename).name != filename
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid recording."
        )

    path = RECORDINGS_DIR / filename

    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Recording not found."
        )

    # Use custom download name if supplied.
    if download_name:
        safe_name = "".join(
            character
            for character in download_name
            if character not in '<>:"/\\|?*'
            and ord(character) >= 32
        ).strip().rstrip(". ")

        if not safe_name:
            safe_name = "Recording"

        safe_name = safe_name[:150]

        if not safe_name.lower().endswith(".wav"):
            safe_name += ".wav"

    else:
        safe_name = filename

    return FileResponse(
        path,
        media_type="audio/wav",
        filename=safe_name
    )



@app.get("/")
def home():
    return FileResponse(FRONTEND_DIR / "index.html")
