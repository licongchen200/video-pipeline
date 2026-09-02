# Landscape research: tools for automating YouTube video production

*The answer to "is there existing open source / AI tooling for this, or do I
build it?" — captured before any code was written. This is the reasoning that
produced [ARCHITECTURE.md](../ARCHITECTURE.md).*

---

## Don't build the platform. Assemble it.

There's a well-trodden path here already. Three different products hide under
"YouTube video," and they want different stacks:

| Goal | Laziest thing that works |
|---|---|
| **SaaS/product ad** | Screen capture (OBS / Screen Studio) or **Playwright** driving your app → **Remotion** for overlays, zooms, captions |
| **Teaching / course** | Slides or screen recording + TTS + auto-captions. **Auto-Editor** to cut silences. Manim if it's math |
| **Faceless AI shorts** | Fork **MoneyPrinterTurbo** or **ShortGPT** — script→TTS→stock footage→captions→upload, already wired |

### The open-source pieces worth knowing

- **Remotion** — React → MP4. The best programmatic video tool that exists.
  Your video is a component, props are the data, render is deterministic.
  Company/product license applies over a certain size.
- **Revideo** / **Motion Canvas** — same idea, TS, animation-first, MIT.
- **ffmpeg** — does 80% of what people install a library for. Concat, overlay,
  burn subtitles, crossfade.
- **faster-whisper / WhisperX** — word-level timestamps. This is how you get
  karaoke captions, and how you sync visuals to narration.
- **Auto-Editor** — one command, deletes all your silences and "umm"s.
- **Piper / Kokoro / F5-TTS / XTTS** local; **ElevenLabs / Cartesia** if you
  want it to not sound like a robot (worth paying here — voice is the #1 thing
  that makes AI video feel cheap).
- **Playwright** for product demos: the demo becomes code, so a UI change means
  re-running a script, not re-recording a human.
- Avatars: HeyGen/Synthesia (API, good), LivePortrait/SadTalker/MuseTalk (open,
  uncanny).
- Generative B-roll: Veo 3 (native audio), Kling, Runway; open-weight: Wan 2.x,
  LTX-Video, HunyuanVideo.
- **Shotstack / Creatomate / json2video** — if you'd rather POST JSON than run
  a render farm.

## If you build it: the architecture

One idea does all the work — **a scene manifest is the only real artifact;
everything else is a pure function over it.**

```
topic ──LLM──> script.yaml ──TTS──> per-scene audio ──whisper──> word timings
                    │                                                  │
                    └──────────> visual spec (render props) <──────────┘
                                          │
                                     render (Remotion/ffmpeg)
                                          │
                                     mux + music + captions
                                          │
                                  YouTube Data API v3
```

Four rules that matter more than the tool choice:

1. **Cache by content hash.** TTS and video-gen calls are the expensive part.
   `hash(text+voice) → wav` in a local dir turns a 4-minute re-render from $3
   into $0. Iteration speed is the whole game.
2. **Audio drives timing, never the reverse.** Generate voice first, measure
   it, then fit visuals. Every pipeline that guesses durations up front ends up
   with visuals drifting off the narration.
3. **Renders must be deterministic.** Same manifest → same MP4. That's why
   programmatic rendering beats "AI generates the whole video" for
   product/teaching content — you can fix scene 7 without rerolling 1–12.
4. **Human in the loop at the script stage.** Approve `script.yaml`, then let
   the rest run headless. The script is 5% of the compute and 95% of whether
   anyone watches.

## Two things that will bite you

**YouTube API quota.** `videos.insert` costs 1600 units against a 10,000/day
default quota — **6 uploads/day** — and quota increases require an audit that
mostly gets denied for bulk-upload use cases. Plan for manual or scheduled
upload if you wanted volume.

**YouTube's monetization policy** (tightened July 2025) explicitly demonetizes
mass-produced, repetitive content. A pipeline that outputs 50 templated videos
a day is building toward a channel that can't be monetized. Aim it at *fewer,
better* videos — the automation should remove tedium from real content, not
manufacture filler.

---

**Start here:** one video, end to end, with the manifest hand-edited before you
write a single line of the LLM script generator.

---

## What actually got built here, and why it differs

The recommendation above says Remotion. This repo doesn't use it. Two reasons,
both about staying on the ladder:

- **Remotion is an npm + React + bundler install** for a project whose visuals
  are stills with text on them. Headless Chrome screenshotting an HTML string
  needs *zero* installs on macOS and gives the same typography engine. Reach
  for Remotion the moment a scene needs real motion — that's the one thing this
  approach genuinely can't do.
- **Whisper isn't installed**, so word-level karaoke captions aren't available.
  Captions are instead drawn into the frame itself at scene granularity, which
  is free and *structurally* cannot desync. See the upgrade path in
  ARCHITECTURE.md.

The four rules above all survived contact with the implementation, and rule 2
(audio drives timing) turned out to be the load-bearing one.
