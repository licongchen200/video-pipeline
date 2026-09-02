"""Stage 1 — narration → WAV, and the measured duration of that WAV.

Audio drives timing for the whole pipeline: we speak first, measure, and only
then decide how long each scene is on screen. Nothing downstream ever guesses
a duration — that is what keeps visuals from drifting off the voice.

Cached by sha256(text, voice, speed), so editing one line of script.yaml
re-synthesizes exactly that line.
"""
import hashlib
import subprocess
import sys
from pathlib import Path

# ponytail: reuses the sibling project's kokoro models rather than a second
# 350MB download. Repoint these two if the projects ever separate.
RECORDER = Path(__file__).resolve().parents[2] / "webapp-recorder"
MODEL = RECORDER / "tts-models" / "kokoro-v1.0.onnx"
VOICES = RECORDER / "tts-models" / "voices-v1.0.bin"


def duration_sec(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def synthesize(scenes, voice, speed, cache_dir):
    """scenes -> [{"wav": Path, "sec": float}], one per scene, in order."""
    if subprocess.run(["which", "ffprobe"], capture_output=True).returncode:
        sys.exit("missing `ffprobe` — brew install ffmpeg")
    if not MODEL.exists() or not VOICES.exists():
        sys.exit(f"kokoro models not found under {MODEL.parent}")

    cache_dir.mkdir(parents=True, exist_ok=True)
    wavs, todo = [], []
    for scene in scenes:
        text = " ".join(scene["narration"].split())
        key = hashlib.sha256(f"{text}|{voice}|{speed}".encode()).hexdigest()[:16]
        wav = cache_dir / f"{key}.wav"
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
        kokoro = Kokoro(str(MODEL), str(VOICES))
        for text, wav in todo:
            samples, rate = kokoro.create(text, voice=voice, speed=float(speed),
                                          lang="en-us")
            sf.write(str(wav), samples, rate)
    else:
        print(f"  tts: all {len(wavs)} line(s) cached")

    return [{"wav": w, "sec": duration_sec(w)} for w in wavs]
