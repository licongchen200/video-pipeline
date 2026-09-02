"""Sidecar subtitle files (.srt / .vtt) — closed captions the viewer can
toggle, as opposed to the open captions burned into each frame.

These are exact rather than approximate, which is unusual: the text is the
same string that was fed to the TTS engine (not a transcription of it), and
the timing comes from ffprobe measuring the synthesized audio (not an
estimate). So the cues are correct by construction.

A scene with `captions: false` still gets a cue. That flag governs what is
painted onto the frame; a caption track is an accessibility surface, and
omitting spoken words from it would defeat the point.
"""


def format_timestamp(seconds, millis_sep=","):
    """SRT wants HH:MM:SS,mmm — WebVTT wants the same with a period."""
    if seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{millis_sep}{ms:03d}"


def build_cues(scenes, audio, pad):
    """[{start, end, text}] — one cue per narrated scene, in order.

    A cue ends when the speech ends, not when the scene does: the trailing
    pad is silence, and leaving the caption up through it makes the text
    look like it lags the voice.
    """
    cues = []
    clock = 0.0
    for scene, a in zip(scenes, audio):
        text = " ".join(scene.get("narration", "").split())
        if text:
            cues.append({"start": clock, "end": clock + a["sec"], "text": text})
        clock += a["sec"] + pad
    return cues


def to_srt(cues):
    blocks = []
    for i, cue in enumerate(cues, start=1):
        blocks.append(
            f"{i}\n"
            f"{format_timestamp(cue['start'])} --> {format_timestamp(cue['end'])}\n"
            f"{cue['text']}\n"
        )
    return "\n".join(blocks)


def to_vtt(cues):
    blocks = ["WEBVTT\n"]
    for cue in cues:
        blocks.append(
            f"{format_timestamp(cue['start'], '.')} --> "
            f"{format_timestamp(cue['end'], '.')}\n"
            f"{cue['text']}\n"
        )
    return "\n".join(blocks)


def write(cues, out_path):
    """Writes <out_path>.srt and .vtt. Returns the .srt path."""
    srt = out_path.with_suffix(".srt")
    srt.write_text(to_srt(cues), encoding="utf-8")
    out_path.with_suffix(".vtt").write_text(to_vtt(cues), encoding="utf-8")
    return srt
