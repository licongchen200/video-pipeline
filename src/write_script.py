#!/usr/bin/env python3
"""Stage 0 (optional) — a topic → a draft script.yaml.

    python3 src/write_script.py "how to use stripe checkout" --seconds 30

This is the only stage with an LLM in it, and deliberately the only one: it
writes a *draft* you read and edit. Everything downstream is deterministic, so
the manifest is the one place a human should still be in the loop. It is 5% of
the runtime and ~100% of whether the video is worth watching.

Never overwrites an existing script — writes script.draft.yaml by default.

Credentials come from webapp-recorder/.env (OPENROUTER_API_KEY,
OPENROUTER_MODEL). stdlib only; no SDK needed for one POST.
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT.parent / "webapp-recorder" / ".env"
API = "https://openrouter.ai/api/v1/chat/completions"
WORDS_PER_SEC = 2.6  # measured against kokoro af_heart at speed 1.05

SYSTEM = """You write scripts for short technical explainer videos.

Return ONLY a JSON object: {"title": str, "scenes": [...]}. Each scene is
{"id": short-slug, "narration": str, "visual": {...}} where visual is one of:

  {"type":"title","text":str,"subtitle":str}
  {"type":"code","label":"file.js","step":"1","lang":"js","code":str}
  {"type":"steps","heading":str,"items":[str,...]}

Rules:
- Total narration MUST be under %(budget)d words. This is a hard limit.
- Open with a title scene, close with a title scene. 4-7 scenes total.
- Narration is spoken aloud: no markdown, no URLs, no symbols. Read digits as
  words ("four two four two", not "4242").
- Code must be real, runnable, and under 8 lines per scene.
- "step" is a single digit character ("1", "2"), never a word. Omit it if the
  scene is not a numbered step.
- The narration explains the code on screen; it does not read it out.
"""


def env(name):
    if name in os.environ:
        return os.environ[name]
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            key, _, val = line.partition("=")
            if key.strip() != name:
                continue
            val = val.strip()
            if val[:1] in "\"'":  # quoted: take the quoted span verbatim
                return val[1:val.index(val[0], 1)]
            return val.split(" #")[0].strip()  # unquoted: trailing comment
    return None


def ask(topic, budget):
    key = env("OPENROUTER_API_KEY")
    if not key:
        sys.exit(f"OPENROUTER_API_KEY not set and not found in {ENV_FILE}")
    body = {
        "model": env("OPENROUTER_MODEL") or "anthropic/claude-sonnet-5",
        "messages": [
            {"role": "system", "content": SYSTEM % {"budget": budget}},
            {"role": "user", "content": f"Write the video script for: {topic}"},
        ],
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        API, data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            payload = json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"OpenRouter {e.code}: {e.read().decode()[:400]}")

    text = payload["choices"][0]["message"]["content"]
    match = re.search(r"\{.*\}", text, re.S)  # models like to wrap JSON in prose
    if not match:
        sys.exit(f"no JSON in model reply:\n{text[:400]}")
    return json.loads(match.group())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("topic")
    ap.add_argument("--seconds", type=int, default=30)
    ap.add_argument("-o", "--out", type=Path, default=ROOT / "script.draft.yaml")
    args = ap.parse_args()

    budget = int(args.seconds * WORDS_PER_SEC)
    draft = ask(args.topic, budget)

    doc = {"title": draft["title"], "voice": "af_heart", "speed": 1.05,
           "fps": 30, "width": 1920, "height": 1080, "captions": True,
           "scene_pad_sec": 0.35, "scenes": draft["scenes"]}

    if args.out.exists():
        sys.exit(f"{args.out} exists — delete it or pass -o somewhere else")
    args.out.write_text(yaml.safe_dump(doc, sort_keys=False, width=88))

    words = sum(len(s["narration"].split()) for s in draft["scenes"])
    print(f"{args.out}  {len(draft['scenes'])} scenes  {words} words "
          f"(~{words / WORDS_PER_SEC:.0f}s, budget {budget})")
    if words > budget:
        print("  over budget — trim narration, or raise `speed` in the yaml")
    print(f"\nRead it, edit it, then:  make VIDEO={args.out}")


if __name__ == "__main__":
    main()
