#!/usr/bin/env python3
"""Applies every fix needed to run SadTalker on this machine (Apple Silicon,
no CUDA) that upstream doesn't ship. Run once by `make avatar-setup-sadtalker`
right after cloning — each patch is idempotent (checked before applied) so a
second run is a no-op, not an error.

Three bug classes, all from this being an unmaintained 2023 repo meeting a
much newer numpy/torchvision:

  1. basicsr's `torchvision.transforms.functional_tensor` import was removed
     upstream (same break Wav2Lip has, different vendor).
  2. Three spots use the legacy `Tensor.type(x.type())` idiom to propagate
     device+dtype — works for cuda/cpu, but MPS isn't representable in that
     legacy type-string API, so it silently downgrades to CPU. `.type_as()`
     is the correct fix for any device, not just MPS.
  3. Two numpy-version breaks: `np.float` was removed in 1.24+, and building
     `np.array([...])` from mixed scalars/1-element-arrays used to silently
     object-array and now raises.
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
ST = ROOT / "vendor" / "SadTalker"
BASICSR_DEGRADATIONS = ROOT / ".sadtalker-venv" / "lib" / "python3.11" / \
    "site-packages" / "basicsr" / "data" / "degradations.py"


def replace_once(path, old, new, label):
    text = path.read_text()
    if new in text:
        return False  # already patched
    if old not in text:
        sys.exit(f"{label}: expected text not found in {path} — "
                 f"upstream changed, patch by hand")
    path.write_text(text.replace(old, new, 1))
    return True


PATCHES = [
    (BASICSR_DEGRADATIONS,
     "from torchvision.transforms.functional_tensor import rgb_to_grayscale",
     "try:\n"
     "    from torchvision.transforms.functional_tensor import rgb_to_grayscale\n"
     "except ImportError:\n"
     "    from torchvision.transforms.functional import rgb_to_grayscale",
     "basicsr functional_tensor"),

    (ST / "src/facerender/modules/util.py",
     "coordinate_grid = make_coordinate_grid(spatial_size, mean.type())",
     "coordinate_grid = make_coordinate_grid(spatial_size, mean)",
     "util.py kp2gaussian call site"),
    (ST / "src/facerender/modules/util.py",
     "def make_coordinate_grid_2d(spatial_size, type):",
     "def make_coordinate_grid_2d(spatial_size, ref):",
     "util.py make_coordinate_grid_2d signature"),
    (ST / "src/facerender/modules/util.py",
     "def make_coordinate_grid(spatial_size, type):",
     "def make_coordinate_grid(spatial_size, ref):",
     "util.py make_coordinate_grid signature"),
    (ST / "src/facerender/modules/util.py",
     "x = torch.arange(w).type(type)\n    y = torch.arange(h).type(type)\n\n    x = (2",
     "x = torch.arange(w).type_as(ref)\n    y = torch.arange(h).type_as(ref)\n\n    x = (2",
     "util.py make_coordinate_grid_2d body"),
    (ST / "src/facerender/modules/util.py",
     "x = torch.arange(w).type(type)\n    y = torch.arange(h).type(type)\n    z = torch.arange(d).type(type)",
     "x = torch.arange(w).type_as(ref)\n    y = torch.arange(h).type_as(ref)\n    z = torch.arange(d).type_as(ref)",
     "util.py make_coordinate_grid body"),

    (ST / "src/facerender/modules/dense_motion.py",
     "identity_grid = make_coordinate_grid((d, h, w), type=kp_source['value'].type())",
     "identity_grid = make_coordinate_grid((d, h, w), kp_source['value'])",
     "dense_motion.py identity_grid call site"),
    (ST / "src/facerender/modules/dense_motion.py",
     ".type(heatmap.type())",
     ".type_as(heatmap)",
     "dense_motion.py zeros background feature"),

    (ST / "src/facerender/modules/keypoint_detector.py",
     "make_coordinate_grid(shape[2:], heatmap.type())",
     "make_coordinate_grid(shape[2:], heatmap)",
     "keypoint_detector.py grid call site"),

    (ST / "inference.py",
     '    if torch.cuda.is_available() and not args.cpu:\n'
     '        args.device = "cuda"\n'
     '    else:\n'
     '        args.device = "cpu"',
     '    if torch.cuda.is_available() and not args.cpu:\n'
     '        args.device = "cuda"\n'
     '    elif torch.backends.mps.is_available() and not args.cpu:\n'
     '        args.device = "mps"\n'
     '    else:\n'
     '        args.device = "cpu"',
     "inference.py device selection"),

    (ST / "src/face3d/util/my_awing_arch.py",
     "preds.astype(np.float, copy=False)",
     "preds.astype(np.float64, copy=False)",
     "my_awing_arch.py np.float removal"),
    (ST / "src/face3d/util/preprocess.py",
     "trans_params = np.array([w0, h0, s, t[0], t[1]])",
     "trans_params = np.array([w0, h0, s, float(t[0]), float(t[1])])",
     "preprocess.py ragged trans_params"),
]


def main():
    applied = 0
    for path, old, new, label in PATCHES:
        if not path.exists():
            sys.exit(f"{label}: {path} does not exist — run the clone/venv "
                     f"steps first")
        if replace_once(path, old, new, label):
            applied += 1
    print(f"patch_sadtalker: {applied} patch(es) applied, "
          f"{len(PATCHES) - applied} already in place")


if __name__ == "__main__":
    main()
