#!/usr/bin/env python3
"""script.yaml → out/<slug>.mp4

    python3 src/build.py [script.yaml] [--out out/video.mp4]

Three stages, each a pure function of the manifest plus a content-hash cache:

    scenes ──tts──> wav + measured duration ─┐
           └─render──> png ─────────────────┴──assemble──> mp4

Run it twice and the second run does almost nothing; edit one narration line
and only that line is re-spoken.
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import assemble as assemble_mod  # noqa: E402
import avatar as avatar_mod  # noqa: E402
import render as render_mod  # noqa: E402
import subtitles as subtitles_mod  # noqa: E402
import tts as tts_mod  # noqa: E402

import yaml  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = {"voice": "af_heart", "speed": 1.0, "fps": 30, "width": 1920,
            "height": 1080, "captions": True, "scene_pad_sec": 0.35}


def load(path):
    cfg = {**DEFAULTS, **yaml.safe_load(path.read_text())}
    scenes = cfg.get("scenes") or []
    if not scenes:
        sys.exit(f"{path}: no scenes")
    for i, scene in enumerate(scenes):
        scene.setdefault("id", f"scene-{i}")
        for field in ("narration", "visual"):
            if not scene.get(field):
                sys.exit(f"{path}: scene {scene['id']!r} is missing {field!r}")
    return cfg, scenes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("script", nargs="?", default=ROOT / "script.yaml", type=Path)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    cfg, scenes = load(args.script)
    slug = re.sub(r"[^a-z0-9]+", "-", cfg["title"].lower()).strip("-")
    out = args.out or ROOT / "out" / f"{slug}.mp4"
    build = ROOT / "build"

    print(f"{cfg['title']} — {len(scenes)} scenes")
    audio = tts_mod.synthesize(scenes, cfg["voice"], cfg["speed"], build / "tts")
    pngs = render_mod.render(scenes, cfg, build / "frames")

    avatar_clips = [None] * len(scenes)
    ac = cfg.get("avatar")
    if ac and ac.get("enabled"):
        wanted = [i for i, s in enumerate(scenes) if s.get("avatar", True)]
        synced = avatar_mod.sync(ROOT / ac["face"], [audio[i] for i in wanted],
                                 build / "avatar", ac.get("engine", "wav2lip"))
        for i, clip in zip(wanted, synced):
            avatar_clips[i] = clip

    total = assemble_mod.assemble(pngs, audio, cfg, build / "clips", out, avatar_clips)

    # Closed captions: a sidecar pair to upload alongside the video, plus a
    # track inside it so any player can toggle them.
    cues = subtitles_mod.build_cues(scenes, audio, cfg["scene_pad_sec"])
    if cues:
        srt = subtitles_mod.write(cues, out)
        assemble_mod.embed_subtitles(out, srt)
        print(f"  subtitles: {len(cues)} cues -> {srt.name} + .vtt, embedded")

    print(f"\n{out.relative_to(Path.cwd()) if out.is_relative_to(Path.cwd()) else out}"
          f"  {total:.1f}s  {out.stat().st_size / 1e6:.1f} MB")
    for scene, a in zip(scenes, audio):
        print(f"  {a['sec'] + cfg['scene_pad_sec']:5.1f}s  {scene['id']}")


if __name__ == "__main__":
    main()
