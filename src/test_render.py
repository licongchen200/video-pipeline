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

print("ok")
