"""Stage 3 — (PNG + WAV [+ avatar MP4]) → one MP4.

Each scene becomes a self-contained clip whose video and audio are cut to the
exact same length, then the clips are concatenated with a stream copy. Doing
it per-scene means no global delay arithmetic to get wrong: a scene is
correct in isolation or it isn't at all.
"""
import subprocess
from pathlib import Path

# x, y (top-left corner) of the SxS avatar circle, in ffmpeg overlay-filter
# expression syntax (W/H are the base frame's own dimensions there).
POSITIONS = {
    "bottom-right": ("W-{s}-{m}", "H-{s}-{m}"),
    "bottom-left": ("{m}", "H-{s}-{m}"),
    "top-right": ("W-{s}-{m}", "{m}"),
    "top-left": ("{m}", "{m}"),
}

# The caption band (render.py's .cap) runs ~190px tall at the bottom of the
# frame. A bottom-positioned avatar needs at least that much margin or the
# circle sits on top of the caption text.
CAPTION_CLEARANCE = 190


def _run(args):
    p = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args],
                       capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(p.stderr.strip()[:2000])


def build_clip(png, wav, sec, cfg, out, avatar=None):
    """One still + one narration line, both exactly `sec` long. `avatar`, if
    given, is {"mp4": Path, "size": int, "margin": int, "position": str} —
    composited as a circular cutout in one corner.
    """
    # All -i inputs must come before any -map: ffmpeg treats an option
    # appearing between two -i's as belonging to the *next* input.
    inputs = ["-framerate", str(cfg["fps"]), "-loop", "1", "-i", str(png)]
    outputs = []

    if avatar:
        s, m = avatar["size"], avatar["margin"]
        x, y = (e.format(s=s, m=m) for e in POSITIONS[avatar["position"]])
        inputs += ["-i", str(avatar["mp4"])]
        outputs += [
            "-filter_complex",
            # tpad holds the avatar's last frame well past `sec` (the exact
            # remainder is trimmed by -t below) so the pad-silence tail
            # freezes instead of looping the mouth or vanishing early.
            f"[1:v]scale={s}:{s},tpad=stop_mode=clone:stop_duration=5,"
            "format=rgba,"
            f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
            f"a='if(lte(pow(X-{s}/2,2)+pow(Y-{s}/2,2),pow({s}/2,2)),255,0)'[circ];"
            f"[0:v][circ]overlay={x}:{y}[vout]",
            "-map", "[vout]",
        ]
    else:
        outputs += ["-map", "0:v", "-tune", "stillimage"]  # only true of the no-avatar path

    inputs += ["-i", str(wav)]
    outputs += ["-map", f"{2 if avatar else 1}:a"]

    args = inputs + outputs + [
        # apad extends the narration with silence to fill the pad at the end
        # of the scene; -t on both streams is what makes the cut land clean.
        "-af", "apad", "-t", f"{sec:.3f}",
        "-r", str(cfg["fps"]),
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        str(out),
    ]
    _run(args)


def assemble(pngs, audio, cfg, work_dir, out_path, avatar_clips=None):
    """Returns the total duration in seconds. `avatar_clips`, if given, is a
    list the same length as `pngs`/`audio` — each entry either None or
    {"mp4": Path} for that scene (see avatar.py).
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    pad = cfg.get("scene_pad_sec", 0.35)
    avatar_cfg = cfg.get("avatar") or {}
    avatar_clips = avatar_clips or [None] * len(pngs)

    clips, total = [], 0.0
    for i, (png, a, ac) in enumerate(zip(pngs, audio, avatar_clips)):
        sec = a["sec"] + pad
        clip = work_dir / f"clip-{i:02d}.mp4"
        avatar = None
        if ac:
            position = avatar_cfg.get("position", "bottom-right")
            default_margin = 48
            if position.startswith("bottom") and cfg.get("captions", True):
                default_margin = CAPTION_CLEARANCE
            avatar = {"mp4": ac["mp4"],
                      "size": avatar_cfg.get("size", 340),
                      "margin": avatar_cfg.get("margin", default_margin),
                      "position": position}
        build_clip(png, a["wav"], sec, cfg, clip, avatar)
        clips.append(clip)
        total += sec

    listing = work_dir / "clips.txt"
    listing.write_text("".join(f"file '{c.resolve()}'\n" for c in clips))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    _run(["-f", "concat", "-safe", "0", "-i", str(listing),
          "-c", "copy", "-movflags", "+faststart", str(out_path)])

    print(f"  assemble: {len(clips)} clips concatenated")
    return total


def embed_subtitles(video_path, srt_path):
    """Adds the subtitle file as a real track inside the video.

    The sidecar .srt is what YouTube wants; this is what makes the captions
    toggleable for anyone who just opens the file (QuickTime, VLC). Audio
    and video are still stream-copied, so it costs a remux, not a re-encode.
    """
    tmp = video_path.with_suffix(".subbed.mp4")
    _run(["-i", str(video_path), "-i", str(srt_path),
          "-map", "0", "-map", "1",
          "-c", "copy", "-c:s", "mov_text",
          "-metadata:s:s:0", "language=eng",
          "-movflags", "+faststart", str(tmp)])
    tmp.replace(video_path)
