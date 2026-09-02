# video-pipeline

`script.yaml` → narrated, captioned 1080p MP4. Fully local: no cloud TTS, no
render service, no API key needed to build a video.

Ships with a working example — a 26.5s "Stripe Checkout in 30 Seconds"
explainer — in [`script.yaml`](script.yaml).

```
make            # script.yaml -> out/stripe-checkout-in-30-seconds.mp4
make open       # ...and play it
make test       # self-check for the syntax highlighter
```

## What it does

```
script.yaml ──▶ kokoro TTS ──▶ wav + measured duration ─┐
            └─▶ HTML → headless Chrome ──▶ 1080p png ───┴─▶ ffmpeg ──▶ mp4
```

Six scenes, ~26 seconds, ~20s to build. Everything is a pure function of
`script.yaml`, cached by content hash — edit one narration line and only that
line is re-spoken.

See [ARCHITECTURE.md](ARCHITECTURE.md) for why it's built this way, and
[docs/search.md](docs/search.md) for the survey of existing tools that led here
(Remotion, ShortGPT, Whisper, and what to use instead of this).

## Requirements

```bash
brew install ffmpeg python@3.13   # ffprobe drives every duration measurement
make setup                        # venv + ~350MB of kokoro TTS weights
make                              # build the example video
```

Also needs **Google Chrome** at the standard `/Applications` path — it's the
renderer.

Already have [webapp-recorder](https://github.com/licongchen200/webapp-recorder)
checked out? Its `tts-models/` holds the identical kokoro pair, so you can skip
that download:

```bash
KOKORO_MODEL_DIR=../webapp-recorder/tts-models make
```

## Writing a script

Every video is one YAML file. Three visual types:

```yaml
title: Stripe Checkout in 30 Seconds
voice: af_heart        # kokoro: af_heart, af_bella, am_michael, bf_emma...
speed: 1.05            # nudge up to fit a time budget
captions: true         # burn the narration into each frame
scene_pad_sec: 0.35    # silence held after each line, so cuts don't clip

scenes:
  - id: hook
    narration: Taking payments with Stripe Checkout is three steps.
    visual: { type: title, text: Stripe Checkout, subtitle: in 30 seconds }

  - id: session
    narration: One. On your server, create a Checkout Session.
    visual:
      type: code
      label: server.js
      step: "1"
      code: |
        const session = await stripe.checkout.sessions.create({ ... });

  - id: test
    narration: Test it with card four two four two, four two four two.
    visual:
      type: steps
      heading: Test card
      items: ["4242 4242 4242 4242", "Any future expiry"]
```

Two rules the pipeline can't enforce for you:

- **Narration is spoken.** Write `four two four two`, not `4242`. No URLs, no
  markdown, no symbols.
- **Don't read the code aloud.** The narration says why; the frame shows what.

Scene length is never specified — it's whatever the narration measures, plus
`scene_pad_sec`. Budget roughly **2.6 words per second**, so 30s ≈ 78 words
total.

## Optional: lip-synced avatar

A talking-head circle overlay, mouth synced to the actual narration audio, via
[Wav2Lip](https://github.com/Rudrabha/Wav2Lip) run locally (CPU, no cloud).
Off by default — nothing about the base pipeline needs it.

```bash
make avatar-setup      # once: clones Wav2Lip, ~450MB of models, ~2 min
```

Then in `script.yaml`:

```yaml
avatar:
  enabled: true
  face: assets/avatar.jpg    # one clear, front-facing photo. You supply this.
  position: bottom-right     # bottom-right | bottom-left | top-right | top-left
  size: 340
  margin: 48
```

Add `avatar: false` on any individual scene (a title/outro card, say) to hide
it just there. `make` picks this up automatically — no separate command.

**The photo is on you, deliberately.** Wav2Lip makes a face say arbitrary
audio — that's exactly what it's for, but it means the pipeline won't fetch
or pick a stranger's photo for you. Use your own, a teammate's with consent,
or a licensed avatar image. One frontal, well-lit, mouth-visible photo is
enough — Wav2Lip holds the head still and animates only the mouth region.

Each scene's clip is cached by `sha256(photo, wav)` — same content-hash
discipline as everything else, so editing narration re-syncs only the
affected scene. Runs on CPU (this repo predates Apple's MPS backend); a few
seconds of audio takes well under a minute to sync on an M-series chip.

## Optional: draft a script with an LLM

```bash
make draft TOPIC="how to add dark mode to a React app"
# -> script.draft.yaml   5 scenes  59 words (~23s, budget 78)
make VIDEO=script.draft.yaml
```

Reads `OPENROUTER_API_KEY` / `OPENROUTER_MODEL` from the environment, falling
back to this project's own `.env` (see `.env.example`) — so
`OPENROUTER_API_KEY=sk-... make draft ...` works with no file at all. It's the
only stage that needs a key; everything else runs fully local.
It writes a **draft** and never overwrites an existing script — read and edit
it before building. This is the only non-deterministic stage in the repo, and
the only one worth keeping a human in.

## Layout

```
script.yaml          the whole video, as data — the only state
src/build.py         orchestrator
src/tts.py           stage 1 — narration → wav + duration    (kokoro)
src/render.py        stage 2 — scene → 1080p png             (HTML + Chrome)
src/assemble.py      stage 3 — png + wav → mp4               (ffmpeg)
src/write_script.py  stage 0 — topic → draft yaml (optional) (OpenRouter)
src/avatar.py         stage 1b — wav + photo → lip-synced clip (optional)   (Wav2Lip)
src/test_render.py   self-check for the syntax highlighter
vendor/Wav2Lip/      cloned by `make avatar-setup` — not our code, gitignore it
.avatar-venv/         Wav2Lip's python deps — reuses global torch/opencv via --system-site-packages
build/               content-hash cache — safe to delete
out/                 finished videos
```

## Gotchas

- **`build/` is a cache, not output.** Delete it freely; it rebuilds.
- **Chrome prints `CVDisplayLinkCreateWithCGDisplay failed`** on every headless
  run. Harmless macOS noise, not an error.
- **Total runtime won't hit an exact target.** Duration comes from the measured
  audio. To fit a hard budget, change `speed` or cut words.
- **No motion, no music, no word-level captions** — see the omissions table in
  ARCHITECTURE.md for when each is worth adding.
