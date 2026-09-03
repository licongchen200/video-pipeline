#!/usr/bin/env python3
"""Self-check for the only non-trivial logic here: the syntax highlighter.

    python3 src/test_render.py

Both cases below are bugs this code actually shipped once — a sequential
str.replace highlighter mangled URLs inside strings and corrupted its own
markup. Run this after touching TOKEN or highlight().
"""
from render import caption_padding, highlight, html

# A URL inside a string is not a comment: the '//' must stay inside the
# string span, not open a comment span that swallows the rest of the line.
out = highlight("success_url: 'https://you.app/done',")
assert "<span class='s'>'https://you.app/done'</span>," == out.split(": ")[1], out
assert "class='c'" not in out, out

# A real comment is a comment.
assert highlight("// hi").startswith("<span class='c'>"), highlight("// hi")

# Keywords are marked, and marking them does not corrupt neighbouring spans.
out = highlight("const x = await f('a');")
assert out.count("<span") == 3, out
assert out.count("</span>") == 3, out
assert "<span class='k'>const</span>" in out, out
assert "<span class='s'>'a'</span>" in out, out

# Keywords only on word boundaries — no mangling identifiers that contain one.
assert "<span" not in highlight("constant = ifx + newton"), \
    highlight("constant = ifx + newton")

# HTML metacharacters are escaped, so code can never inject into the page.
assert highlight("if (a<b && c>d)").count("<span") == 1
assert "&lt;b &amp;&amp; c&gt;" in highlight("if (a<b && c>d)")

# Apostrophes survive escaping well enough for the string rule to still fire.
assert "class='s'" in highlight("x = 'it';")

# Unknown visual types fail loudly rather than rendering an empty frame.
try:
    html({"narration": "x", "visual": {"type": "nope"}},
         {"width": 1920, "height": 1080})
    raise AssertionError("expected ValueError for unknown visual type")
except ValueError:
    pass

# Captions are burned into the frame markup when enabled, absent when not.
scene = {"narration": "hello  there", "visual": {"type": "title", "text": "T"}}
cfg = {"width": 1920, "height": 1080}
assert "hello there" in html(scene, {**cfg, "captions": True})
assert "hello there" not in html(scene, {**cfg, "captions": False})

# A scene-level "captions" wins over the global default either direction.
assert "hello there" not in html({**scene, "captions": False}, {**cfg, "captions": True})
assert "hello there" in html({**scene, "captions": True}, {**cfg, "captions": False})

# A bottom-corner avatar reserves caption width on its own side, so long
# lines wrap instead of running underneath the circle.
assert caption_padding({}) == (200, 200), caption_padding({})
assert caption_padding({"avatar": {"enabled": False, "size": 340}}) == (200, 200)

right_cfg = {"avatar": {"enabled": True, "size": 340, "margin": 40,
                        "position": "bottom-right"}}
assert caption_padding(right_cfg) == (200, 420), caption_padding(right_cfg)

left_cfg = {**right_cfg, "avatar": {**right_cfg["avatar"], "position": "bottom-left"}}
assert caption_padding(left_cfg) == (420, 200), caption_padding(left_cfg)

# A top-corner avatar never overlaps the caption bar — no reservation.
top_cfg = {**right_cfg, "avatar": {**right_cfg["avatar"], "position": "top-right"}}
assert caption_padding(top_cfg) == (200, 200), caption_padding(top_cfg)

# The reservation reaches the rendered CSS.
page = html({"narration": "x", "visual": {"type": "title", "text": "T"}},
            {"width": 1920, "height": 1080, **right_cfg})
assert "padding:0 420px 54px 200px" in page, page[:400]

from subtitles import build_cues, format_timestamp, to_srt, to_vtt  # noqa: E402

# SRT uses a comma before milliseconds, WebVTT a period — mixing them up
# produces a file players silently ignore.
assert format_timestamp(0) == "00:00:00,000"
assert format_timestamp(3.3) == "00:00:03,300"
assert format_timestamp(3.3, ".") == "00:00:03.300"
assert format_timestamp(61.5) == "00:01:01,500"
assert format_timestamp(3661.25) == "01:01:01,250"
assert format_timestamp(-1) == "00:00:00,000", "negative clamps, never wraps"
# Rounding must carry into seconds, not print 999.5ms as ",1000"
assert format_timestamp(1.9996) == "00:00:02,000"

_scenes = [
    {"narration": "First line."},
    {"narration": "Second  line."},          # collapses whitespace
    {"narration": "", "id": "silent"},        # no cue for a silent scene
    {"narration": "Fourth line.", "captions": False},  # still gets a cue
]
_audio = [{"sec": 2.0}, {"sec": 3.0}, {"sec": 1.0}, {"sec": 2.5}]
_cues = build_cues(_scenes, _audio, 0.5)

assert len(_cues) == 3, _cues
# Cue ends at the end of speech, not the end of the padded scene.
assert _cues[0] == {"start": 0.0, "end": 2.0, "text": "First line."}, _cues[0]
# Next scene starts after the previous scene's speech *and* its pad.
assert _cues[1]["start"] == 2.5, _cues[1]
assert _cues[1]["text"] == "Second line."
# The silent scene consumes its own duration AND its pad, even though it
# produces no cue: 2.5 + 3.0 + 0.5 (scene 1) + 1.0 + 0.5 (scene 2) = 7.5.
assert _cues[2]["start"] == 7.5, _cues[2]
# captions:false suppresses the burned-in text, never the accessibility track.
assert _cues[2]["text"] == "Fourth line."

_srt = to_srt(_cues)
assert _srt.startswith("1\n00:00:00,000 --> 00:00:02,000\nFirst line."), _srt[:80]
assert "\n3\n" in _srt, "cues are numbered from 1, consecutively"
assert to_vtt(_cues).startswith("WEBVTT\n"), "a VTT without its header is invalid"
assert "-->" in to_vtt(_cues) and "," not in to_vtt(_cues).split("-->")[0][-12:]

import os  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

from tts import cache_key  # noqa: E402

# The TTS cache key must cover everything that changes the audio and nothing
# that doesn't. Getting the second half wrong is expensive: a spurious miss
# re-synthesizes, which produces fresh bytes, which misses the avatar cache
# too — a ~30 minute lip-sync re-render for no reason.
with tempfile.TemporaryDirectory() as _d:
    _d = Path(_d)
    _model, _voices = _d / "m.onnx", _d / "v.bin"
    _model.write_bytes(b"x" * 100)
    _voices.write_bytes(b"y" * 50)
    _base = cache_key("hello", "af_heart", 1.0, _model, _voices)

    assert _base == cache_key("hello", "af_heart", 1.0, _model, _voices), "stable"
    assert _base != cache_key("hi", "af_heart", 1.0, _model, _voices), "text matters"
    assert _base != cache_key("hello", "af_bella", 1.0, _model, _voices), "voice matters"
    assert _base != cache_key("hello", "af_heart", 1.1, _model, _voices), "speed matters"

    # Same bytes reached by another path — a symlink, or KOKORO_MODEL_DIR
    # pointing at a sibling checkout — must NOT invalidate.
    _link_dir = _d / "link"
    _link_dir.mkdir()
    os.symlink(_model, _link_dir / "m.onnx")
    os.symlink(_voices, _link_dir / "v.bin")
    assert _base == cache_key("hello", "af_heart", 1.0,
                              _link_dir / "m.onnx", _link_dir / "v.bin"), \
        "a different path to identical models must reuse the cache"

    # A genuinely different model must invalidate.
    _other = _d / "other.onnx"
    _other.write_bytes(b"x" * 101)
    assert _base != cache_key("hello", "af_heart", 1.0, _other, _voices), \
        "a different model must not serve audio made by the old one"

print("ok")
