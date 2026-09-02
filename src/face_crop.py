#!/usr/bin/env python3
"""Crop a photo to a square centred on its face.

    face_crop.py <in.jpg> <out.jpg> [pad]

Runs in the Wav2Lip venv, reusing the S3FD detector that repo already ships
(same detector its own inference.py uses) — no new dependency.

Why this exists: Wav2Lip returns its *input image verbatim* with only the
mouth region repainted, so whatever framing goes in is the framing that ends
up on screen. Handing it a full portrait meant the circular avatar showed a
small face surrounded by background, and squashed it on top of that (a
608x510 source forced into a square loses ~16% of its width). SadTalker
looks better purely because it crops to a 256x256 face itself.

Cropping the source to a square face box fixes both at once and makes the
two engines visually interchangeable.
"""
import sys
from pathlib import Path

import cv2
import numpy as np

# face_detection is a package inside the vendored Wav2Lip repo, not an
# installed dependency — python puts *this* script's directory on sys.path,
# so point it at the repo explicitly rather than relying on the cwd.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vendor" / "Wav2Lip"))
import face_detection  # noqa: E402


def face_box(image, device="cpu"):
    detector = face_detection.FaceAlignment(
        face_detection.LandmarksType._2D, flip_input=False, device=device)
    boxes = detector.get_detections_for_batch(np.array([image]))
    if not boxes or boxes[0] is None:
        return None
    return boxes[0]  # (x1, y1, x2, y2)


def square_crop(image, box, pad):
    """Square box centred on the face, grown by `pad` (fraction of face size)
    to include hair and chin the way SadTalker's own crop does, then clamped
    to stay inside the image."""
    h, w = image.shape[:2]
    x1, y1, x2, y2 = box
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    side = max(x2 - x1, y2 - y1) * (1 + pad)
    # Never larger than the image, or the clamp below would just re-frame it.
    side = min(side, w, h)
    # Bias upward slightly: a face box centres on the eyes/nose, and framing
    # that dead-centre crops the chin while leaving dead space above the head.
    cy += side * 0.08

    left = int(round(min(max(cx - side / 2, 0), w - side)))
    top = int(round(min(max(cy - side / 2, 0), h - side)))
    s = int(round(side))
    return image[top:top + s, left:left + s]


def main():
    if len(sys.argv) < 3:
        sys.exit("usage: face_crop.py <in> <out> [pad]")
    src, dst = sys.argv[1], sys.argv[2]
    pad = float(sys.argv[3]) if len(sys.argv) > 3 else 0.8

    image = cv2.imread(src)
    if image is None:
        sys.exit(f"could not read image: {src}")

    box = face_box(image)
    if box is None:
        # Better a centred square than a stretched portrait: fall back rather
        # than fail, since a mis-detected face shouldn't block the render.
        h, w = image.shape[:2]
        side = min(h, w)
        cropped = image[(h - side) // 2:(h + side) // 2,
                        (w - side) // 2:(w + side) // 2]
        print("no face detected — centre-cropped instead", file=sys.stderr)
    else:
        cropped = square_crop(image, box, pad)

    if not cv2.imwrite(dst, cropped):
        sys.exit(f"could not write image: {dst}")
    print(f"{cropped.shape[1]}x{cropped.shape[0]}")


if __name__ == "__main__":
    main()
