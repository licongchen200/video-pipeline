"""Stage 1 — narration → WAV, and the measured duration of that WAV.

Audio drives timing for the whole pipeline: we speak first, measure, and only
then decide how long each scene is on screen. Nothing downstream ever guesses
a duration — that is what keeps visuals from drifting off the voice.

Cached by sha256(text, voice, speed), so editing one line of script.yaml
re-synthesizes exactly that line.
"""
import hashlib
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _model_dir():
    """Where the kokoro model and voices live.

    This project's own `models/` by default, so a fresh clone works with
    nothing beside it. KOKORO_MODEL_DIR overrides — useful because the
    sibling webapp-recorder ships the same ~350MB pair, and pointing at an
    existing copy beats downloading it twice:

        KOKORO_MODEL_DIR=../webapp-recorder/tts-models make
    """
    override = os.environ.get("KOKORO_MODEL_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return ROOT / "models"


MODEL_NAME = "kokoro-v1.0.onnx"
VOICES_NAME = "voices-v1.0.bin"


def duration_sec(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def cache_key(text, voice, speed, model, voices):
    """Everything that determines the audio, and nothing that doesn't.

    The model is identified by file *size*, deliberately not by path. Its
    path is not stable — KOKORO_MODEL_DIR, a `models` symlink into another
    checkout, and a plain `make setup` are three different strings for the
    same bytes — and a path-keyed cache would miss on all of them. A miss
    isn't just a re-synthesis either: fresh audio means fresh bytes, and the
    avatar cache keys on those, so a spurious miss cascades into a full
    lip-sync re-render. Size changes when the model actually changes, which
    is the thing worth invalidating on.
    """
    fingerprint = f"{model.stat().st_size}:{voices.stat().st_size}"
    return hashlib.sha256(
        f"{text}|{voice}|{speed}|{fingerprint}".encode()).hexdigest()[:16]


def synthesize(scenes, voice, speed, cache_dir):
    """scenes -> [{"wav": Path, "sec": float}], one per scene, in order."""
    if subprocess.run(["which", "ffprobe"], capture_output=True).returncode:
        sys.exit("missing `ffprobe` — brew install ffmpeg")
    model_dir = _model_dir()
    model, voices = model_dir / MODEL_NAME, model_dir / VOICES_NAME
    if not model.exists() or not voices.exists():
        sys.exit(f"kokoro models not found in {model_dir}\n"
                 f"run `make setup`, or point KOKORO_MODEL_DIR at an existing copy")

    cache_dir.mkdir(parents=True, exist_ok=True)
    wavs, todo = [], []
    for scene in scenes:
        text = " ".join(scene["narration"].split())
        wav = cache_dir / f"{cache_key(text, voice, speed, model, voices)}.wav"
        if not wav.exists():
            todo.append((text, wav))
        wavs.append(wav)

    if todo:
        print(f"  tts: synthesizing {len(todo)} line(s), "
              f"{len(wavs) - len(todo)} cached")
        # Imported lazily: loading the 325MB ONNX graph costs ~5s, and a fully
        # cached run should never pay it.
        from kokoro_onnx import Kokoro
        import soundfile as sf
        kokoro = Kokoro(str(model), str(voices))
        for text, wav in todo:
            samples, rate = kokoro.create(text, voice=voice, speed=float(speed),
                                          lang="en-us")
            sf.write(str(wav), samples, rate)
    else:
        print(f"  tts: all {len(wavs)} line(s) cached")

    return [{"wav": w, "sec": duration_sec(w)} for w in wavs]
