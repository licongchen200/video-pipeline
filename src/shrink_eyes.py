#!/usr/bin/env python3
"""Shrink the eyes in a portrait — a small, controllable touch-up, not a
face swap. Always writes a NEW file; the source is never modified.

    shrink_eyes.py <in> <out> [strength] [pad]

    strength  0..1, default 0.15 — 0 is a no-op, 0.25+ starts looking
              obviously edited. Small values (0.1-0.2) read as natural.
    pad       eye-region radius as a multiple of eye width, default 2.2 —
              wider pad blends further into surrounding skin/glasses.

Detects 68 face landmarks (FAN) and applies a radial "pinch" warp centered
on each eye: pixels within the region are pulled inward toward the eye's
center, with a falloff that goes to exactly zero at the region boundary —
so the result blends seamlessly into the surrounding face with no visible
seam, rather than looking like a pasted-in smaller eye.

Needs the SadTalker venv (face_alignment + opencv already live there):
    .sadtalker-venv/bin/python3 src/shrink_eyes.py assets/me.jpg assets/me-smaller-eyes.jpg
"""
import sys

import cv2
import numpy as np


def shrink_eyes(image, strength=0.15, pad=2.2):
    """image: BGR or BGRA ndarray (as from cv2.imread). Returns a new array;
    `image` itself is never modified."""
    import face_alignment

    bgr = image[:, :, :3] if image.shape[2] == 4 else image
    detector = face_alignment.FaceAlignment(
        face_alignment.LandmarksType.TWO_D, flip_input=False, device="cpu")
    preds = detector.get_landmarks(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    if not preds:
        raise ValueError("no face detected")
    lm = preds[0]  # 68x2, ibug order

    eyes = {"right": lm[36:42], "left": lm[42:48]}  # subject's right/left
    h, w = bgr.shape[:2]
    out = image.copy().astype(np.float32)
    map_x, map_y = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))

    for pts in eyes.values():
        cx, cy = pts.mean(axis=0)
        eye_w = np.linalg.norm(pts[0] - pts[3])  # outer to inner corner
        radius = eye_w * pad

        dx, dy = map_x - cx, map_y - cy
        dist = np.sqrt(dx**2 + dy**2)
        mask = dist < radius
        t = np.clip(dist[mask] / radius, 1e-6, 1.0)
        # t' = t^(1-strength): equals t at the boundary (t=1) regardless of
        # strength, which is what guarantees the seamless blend. Inside the
        # boundary it pulls source samples from further out than the output
        # position, which is what reads as "smaller" — the content that
        # used to be near the center now has to squeeze from a wider area.
        scale = np.power(t, 1.0 - strength) / t
        map_x[mask] = cx + dx[mask] * scale
        map_y[mask] = cy + dy[mask] * scale

    for c in range(out.shape[2]):
        out[:, :, c] = cv2.remap(out[:, :, c], map_x, map_y, cv2.INTER_LINEAR,
                                 borderMode=cv2.BORDER_REPLICATE)
    return out.astype(np.uint8)


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    src, dst = sys.argv[1], sys.argv[2]
    strength = float(sys.argv[3]) if len(sys.argv) > 3 else 0.15
    pad = float(sys.argv[4]) if len(sys.argv) > 4 else 2.2

    image = cv2.imread(src, cv2.IMREAD_UNCHANGED)  # keep alpha if present
    if image is None:
        sys.exit(f"could not read image: {src}")

    try:
        result = shrink_eyes(image, strength, pad)
    except ValueError as e:
        sys.exit(str(e))

    if not cv2.imwrite(dst, result):
        sys.exit(f"could not write image: {dst}")
    print(dst)


if __name__ == "__main__":
    main()
