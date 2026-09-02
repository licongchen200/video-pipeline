"""Stage 1b (optional) — one face photo + per-scene narration → a lip-synced
talking-head clip per scene.

Runs after stage 1 (tts.py), not instead of it: both engines need the exact
wav that will actually play, so lip-sync can't run before narration exists.
Both are given a *static image*, which makes them hold the head still and
only animate the mouth region.

Two engines, same cache discipline — sha256(photo bytes, wav bytes), one
subdirectory per engine so switching `avatar.engine` in script.yaml can't
serve one engine's clip under the other's key:

    wav2lip   — fast (~20s for a 26s video), CPU, GAN-pasted mouth patch.
                Visibly a patch — the honest ceiling of this approach.
    sadtalker — slow (~5s/frame — a 26s video is ~30min), MPS-accelerated,
                full-face 3D-aware render. Much more convincing.
"""
import hashlib
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _hash_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


# --- Wav2Lip ---------------------------------------------------------------

W2L_DIR = ROOT / "vendor" / "Wav2Lip"
W2L_PYTHON = ROOT / ".avatar-venv" / "bin" / "python3"
W2L_CHECKPOINT = W2L_DIR / "checkpoints" / "wav2lip_gan.pth"


def _face_cropped(photo, cache_dir):
    """Square, face-centred crop of the source photo — wav2lip only.

    Wav2Lip repaints the mouth of its input image and hands the rest back
    verbatim, so a full portrait going in means a small face surrounded by
    background coming out, squashed on top of that when the circular cutout
    forces it square. SadTalker crops to the face itself, which is the only
    reason the two engines used to look different.
    """
    out = cache_dir / f"face-{_hash_file(photo)}.jpg"
    if not out.exists():
        p = subprocess.run(
            [str(W2L_PYTHON), str(ROOT / "src" / "face_crop.py"), str(photo), str(out)],
            capture_output=True, text=True)
        if p.returncode or not out.exists():
            # A bad crop shouldn't block a render — fall back to the original.
            print(f"  face crop failed, using the photo as-is:\n{p.stderr[-400:]}",
                  file=sys.stderr)
            return photo
    return out


def _sync_wav2lip(photo, a, out):
    if not W2L_PYTHON.exists():
        sys.exit(".avatar-venv not found — run `make avatar-setup` first")
    if not W2L_CHECKPOINT.exists():
        sys.exit(f"Wav2Lip checkpoint not found at {W2L_CHECKPOINT}\n"
                 f"run `make avatar-setup`")
    tmp = out.with_suffix(".tmp.mp4")
    # Runs on CPU: this repo's device selection predates MPS and hardcodes
    # cuda-or-cpu. Fine at this clip length (seconds, not minutes).
    p = subprocess.run(
        [str(W2L_PYTHON), "inference.py",
         "--checkpoint_path", str(W2L_CHECKPOINT),
         "--face", str(photo), "--audio", str(Path(a["wav"]).resolve()),
         "--outfile", str(tmp.resolve()),
         "--pads", "0", "20", "0", "0",  # a bit more chin, standard tweak for the GAN checkpoint
         # small batches: this machine is tight on RAM/disk, and the default
         # batch size (128) held every frame of a scene in memory at once,
         # which is what drove swap through the roof
         "--wav2lip_batch_size", "8", "--face_det_batch_size", "4"],
        cwd=W2L_DIR, capture_output=True, text=True)
    if p.returncode or not tmp.exists():
        sys.exit(f"Wav2Lip failed on {a['wav'].name}:\n{p.stderr[-2000:]}")
    tmp.rename(out)


# --- SadTalker ---------------------------------------------------------------

ST_DIR = ROOT / "vendor" / "SadTalker"
ST_PYTHON = ROOT / ".sadtalker-venv" / "bin" / "python3"
ST_CHECKPOINTS = ST_DIR / "checkpoints"


def _free_disk_kb():
    return int(shutil.disk_usage("/").free / 1024)


def _wait_for_disk_headroom(min_kb=2_000_000, max_wait_sec=240):
    # Each SadTalker call briefly balloons macOS's swap file (observed: one
    # isolated clip pushed swap to ~6.8GB; back-to-back scenes climbed to
    # ~9.9GB because the OS hadn't reclaimed the previous scene's swap
    # before the next scene added its own pressure). Gating each call on
    # real headroom — not just running them back-to-back — is what keeps
    # a 6-scene build from compounding toward the disk floor.
    waited = 0
    while _free_disk_kb() < min_kb and waited < max_wait_sec:
        time.sleep(5)
        waited += 5
    if _free_disk_kb() < min_kb:
        sys.exit(f"disk still under {min_kb // 1000}MB free after "
                 f"{max_wait_sec}s wait — stopping before it hits zero")


def _sync_sadtalker(photo, a, out):
    if not ST_PYTHON.exists():
        sys.exit(".sadtalker-venv not found — run `make avatar-setup-sadtalker` first")
    if not ST_CHECKPOINTS.exists():
        sys.exit(f"SadTalker checkpoints not found at {ST_CHECKPOINTS}\n"
                 f"run `make avatar-setup-sadtalker`")
    _wait_for_disk_headroom()
    # A scratch --result_dir per call: SadTalker names its own output file by
    # timestamp, not a path we choose, so an empty temp dir is what makes
    # "the one *.mp4 in here" unambiguous afterward.
    with tempfile.TemporaryDirectory() as result_dir:
        p = subprocess.run(
            [str(ST_PYTHON), "inference.py",
             "--checkpoint_dir", str(ST_CHECKPOINTS),
             "--source_image", str(photo.resolve()),
             "--driven_audio", str(Path(a["wav"]).resolve()),
             "--result_dir", result_dir,
             "--still", "--preprocess", "crop", "--size", "256"],
            cwd=ST_DIR, capture_output=True, text=True)
        produced = list(Path(result_dir).glob("*.mp4"))
        if p.returncode or not produced:
            sys.exit(f"SadTalker failed on {a['wav'].name}:\n{p.stderr[-2000:]}")
        shutil.move(str(produced[0]), str(out))


ENGINES = {"wav2lip": _sync_wav2lip, "sadtalker": _sync_sadtalker}


def sync(photo, audio, cache_dir, engine="wav2lip"):
    """audio -> [{"mp4": Path, ...}], one lip-synced clip per scene, in order.

    `audio` is stage 1's output: [{"wav": Path, "sec": float}, ...].
    """
    if engine not in ENGINES:
        sys.exit(f"unknown avatar.engine {engine!r} — pick one of {list(ENGINES)}")
    # Absolute, once, here: both engines run their inference.py with cwd set
    # to their own vendored repo, so a relative path would resolve against
    # that directory instead of the caller's.
    photo = Path(photo).resolve()
    if not photo.exists():
        sys.exit(f"avatar.face not found: {photo}")

    cache_dir = cache_dir / engine
    cache_dir.mkdir(parents=True, exist_ok=True)
    if engine == "wav2lip":
        photo = _face_cropped(photo, cache_dir)
    photo_key = _hash_file(photo)

    clips, made = [], 0
    for a in audio:
        key = hashlib.sha256(f"{photo_key}|{_hash_file(a['wav'])}".encode()).hexdigest()[:16]
        clip = cache_dir / f"{key}.mp4"
        if not clip.exists():
            ENGINES[engine](photo, a, clip)
            made += 1
        clips.append({"mp4": clip, "sec": a["sec"]})

    # stderr, not stdout: the CLI below emits machine-readable JSON on stdout,
    # and a progress line mixed into it would corrupt the parse.
    print(f"  avatar ({engine}): {made} clip(s) lip-synced, {len(clips) - made} cached",
          file=sys.stderr)
    return clips


def main():
    """CLI so a non-Python caller can reuse these engines without
    reimplementing them — see webapp-recorder/src/avatar.js.

        avatar.py <photo> <cache_dir> <engine> <wav> [<wav> ...]

    Prints one JSON line: [{"mp4": ..., "sec": ...}, ...], in input order.
    """
    import json

    if len(sys.argv) < 5:
        sys.exit("usage: avatar.py <photo> <cache_dir> <engine> <wav>...")
    photo, cache_dir, engine, wavs = sys.argv[1], Path(sys.argv[2]), sys.argv[3], sys.argv[4:]
    audio = [{"wav": Path(w), "sec": _duration_sec(w)} for w in wavs]
    clips = sync(photo, audio, cache_dir, engine)
    print(json.dumps([{"mp4": str(c["mp4"]), "sec": c["sec"]} for c in clips]))


def _duration_sec(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True).stdout
    return float(out.strip())


if __name__ == "__main__":
    main()
