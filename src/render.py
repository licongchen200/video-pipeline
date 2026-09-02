"""Stage 2 — scene spec → a 1920x1080 PNG.

HTML/CSS is the layout engine, headless Chrome is the rasterizer. Both are
already on the machine, and nothing beats a browser for code typography.

Deterministic: the same visual spec always produces the same PNG, so it is
cached by hash of the spec. Captions are drawn into the frame itself, which
means they can never drift out of sync with the audio.
"""
import hashlib
import re
import subprocess
import sys
from html import escape
from pathlib import Path

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# One accent, one dark ground, one type scale. Restraint reads as designed;
# five colors read as a template.
CSS = """
*{margin:0;padding:0;box-sizing:border-box}
:root{--bg:#0A0A12;--fg:#F2F2F7;--dim:#8A8AA0;--accent:#635BFF;--panel:#15151F}
body{width:{W}px;height:{H}px;background:var(--bg);color:var(--fg);
  font:400 32px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  display:flex;flex-direction:column;overflow:hidden}
body::before{content:'';position:absolute;top:-25%;left:50%;width:1100px;
  height:1100px;transform:translateX(-50%);border-radius:50%;
  background:radial-gradient(circle,rgba(99,91,255,.20),transparent 62%)}
.stage{flex:1;display:flex;flex-direction:column;justify-content:center;
  padding:0 130px;position:relative;z-index:1}

/* title */
.title h1{font-size:132px;font-weight:700;letter-spacing:-.035em}
.title .sub{font-size:52px;color:var(--dim);margin-top:26px;font-weight:400}
.rule{width:120px;height:8px;background:var(--accent);border-radius:4px;
  margin-bottom:44px}

/* code */
.head{display:flex;align-items:center;gap:22px;margin-bottom:34px}
.step{width:62px;height:62px;flex:none;border-radius:50%;
  background:var(--accent);color:#fff;font-size:32px;font-weight:700;
  display:flex;align-items:center;justify-content:center}
.label{font:500 30px ui-monospace,'SF Mono',Menlo,monospace;color:var(--dim)}
pre{background:var(--panel);border:1px solid #262636;border-radius:20px;
  padding:46px 52px;font:400 36px/1.62 ui-monospace,'SF Mono',Menlo,monospace;
  white-space:pre-wrap;word-break:break-word}
.k{color:#C4B5FD}.s{color:#7DD3A0}.c{color:#5C5C72;font-style:italic}

/* steps */
h2{font-size:74px;font-weight:700;letter-spacing:-.03em;margin-bottom:44px}
li{list-style:none;display:flex;align-items:center;gap:26px;
  font:400 46px ui-monospace,'SF Mono',Menlo,monospace;padding:20px 0}
li::before{content:'';width:16px;height:16px;flex:none;border-radius:50%;
  background:var(--accent)}

/* caption bar — same image as the visual, so it cannot desync */
.cap{flex:none;min-height:150px;display:flex;align-items:center;
  justify-content:center;padding:0 {CAPR}px 54px {CAPL}px;text-align:center;
  font-size:40px;line-height:1.4;color:#C9C9DB;position:relative;z-index:1}
"""

# Comment | string | keyword, in that order. A single left-to-right pass is
# what makes it correct: the string alternative claims 'https://x' before the
# comment rule can see the '//' inside it, and because spans are emitted once
# at the end, no pass can corrupt another pass's markup.
TOKEN = re.compile(
    r"(?P<c>//[^\n]*)"
    r"|(?P<s>'[^'\n]*')"
    r"|(?P<k>\b(?:const|await|async|function|return|new|let|if|await)\b)")


def highlight(code):
    """Three-token syntax coloring. Enough at 36px; a real lexer is not."""
    # quote=False so the string rule still sees real apostrophes.
    escaped = escape(code.rstrip(), quote=False)
    return TOKEN.sub(lambda m: f"<span class='{m.lastgroup}'>{m.group()}</span>",
                     escaped)


def body(visual):
    kind = visual["type"]
    if kind == "title":
        sub = visual.get("subtitle")
        return ("<div class='stage title'><div class='rule'></div>"
                f"<h1>{escape(visual['text'])}</h1>"
                + (f"<div class='sub'>{escape(sub)}</div>" if sub else "")
                + "</div>")
    if kind == "code":
        step = visual.get("step")
        return ("<div class='stage'><div class='head'>"
                + (f"<div class='step'>{escape(step)}</div>" if step else "")
                + f"<div class='label'>{escape(visual.get('label', ''))}</div></div>"
                f"<pre>{highlight(visual['code'])}</pre></div>")
    if kind == "steps":
        items = "".join(f"<li>{escape(i)}</li>" for i in visual["items"])
        return (f"<div class='stage'><h2>{escape(visual['heading'])}</h2>"
                f"<ul>{items}</ul></div>")
    raise ValueError(f"unknown visual type: {kind!r}")


def caption_padding(cfg):
    """(left, right) px for the caption bar.

    A bottom-corner avatar is composited over this frame later (assemble.py),
    so the caption has to give up that much width on that side — otherwise a
    long line runs underneath the circle and the last words are unreadable.
    Reserving the space makes it wrap instead.
    """
    left = right = 200
    avatar = cfg.get("avatar") or {}
    position = avatar.get("position", "bottom-right")
    if avatar.get("enabled") and position.startswith("bottom"):
        reserve = avatar.get("size", 340) + avatar.get("margin", 48) + 40  # +gap
        if position.endswith("right"):
            right = max(right, reserve)
        else:
            left = max(left, reserve)
    return left, right


def html(scene, cfg):
    caption = ""
    if scene.get("captions", cfg.get("captions", True)):
        text = " ".join(scene["narration"].split())
        caption = f"<div class='cap'>{escape(text)}</div>"
    left, right = caption_padding(cfg)
    css = (CSS.replace("{W}", str(cfg["width"])).replace("{H}", str(cfg["height"]))
              .replace("{CAPL}", str(left)).replace("{CAPR}", str(right)))
    return f"<meta charset=utf-8><style>{css}</style>{body(scene['visual'])}{caption}"


def render(scenes, cfg, cache_dir):
    """scenes -> [Path], one PNG each, in order."""
    if not Path(CHROME).exists():
        sys.exit(f"Google Chrome not found at {CHROME}")
    cache_dir.mkdir(parents=True, exist_ok=True)

    pngs, made = [], 0
    for scene in scenes:
        page = html(scene, cfg)
        key = hashlib.sha256(page.encode()).hexdigest()[:16]
        png = cache_dir / f"{key}.png"
        if not png.exists():
            src = cache_dir / f"{key}.html"
            src.write_text(page)
            subprocess.run(
                [CHROME, "--headless", "--disable-gpu", "--hide-scrollbars",
                 "--force-device-scale-factor=1",
                 f"--window-size={cfg['width']},{cfg['height']}",
                 f"--screenshot={png}", src.as_uri()],
                capture_output=True, check=True)
            if not png.exists():
                sys.exit(f"Chrome produced no PNG for scene {scene['id']!r}")
            made += 1
        pngs.append(png)

    print(f"  render: {made} frame(s) drawn, {len(pngs) - made} cached")
    return pngs
