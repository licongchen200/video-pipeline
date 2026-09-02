# Architecture

## The one idea

**`script.yaml` is the only state. Every stage is a pure function of it.**

Nothing else in the repo remembers anything. `build/` is a cache you can
delete at any time, `out/` is disposable output. Delete both and rebuild and
you get a byte-similar video back.

That single property buys everything else: caching is trivially safe, a broken
scene can be fixed without touching the other five, and the whole pipeline is
reviewable by reading one YAML file.

```
                    ┌──────────────┐
   topic ──stage 0─▶│ script.yaml  │◀── you edit this, by hand
    (LLM, optional) └──────┬───────┘
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
      ┌───────────────┐         ┌───────────────┐
      │ stage 1  tts  │         │ stage 2 render│
      │ kokoro-onnx   │         │ HTML→Chrome   │
      └───────┬───────┘         └───────┬───────┘
              │                         │
        wav + measured             1920×1080 png
          duration                  (caption baked in)
              │                         │
              └────────────┬────────────┘
                           ▼
                   ┌───────────────┐
                   │ stage 3       │
                   │ assemble ffmpeg│
                   └───────┬───────┘
                           ▼
                      out/*.mp4
```

## Stage by stage

| Stage | File | In → Out | Cache key |
|---|---|---|---|
| 0 (opt) | `write_script.py` | topic → `script.draft.yaml` | none — you review it |
| 1 | `tts.py` | narration → `wav` + duration | `sha256(text, voice, speed)` |
| 1b (opt) | `avatar.py` | photo + wav → lip-synced `mp4` | `sha256(photo, wav)` |
| 2 | `render.py` | visual spec → `png` | `sha256(rendered html)` |
| 3 | `assemble.py` | png + wav [+ avatar mp4] → `mp4` | none — cheap, always runs |
| — | `build.py` | orchestrates the above | — |

Stages 1 and 2 are independent and could run in parallel; at six scenes it
isn't worth the code.

## The four decisions that carry the design

### 1. Audio drives timing. Always.

We synthesize the narration **first**, `ffprobe` its real duration, and only
then decide how long the frame stays on screen:

```python
scene_duration = measured_narration_duration + scene_pad_sec
```

Every pipeline that instead guesses durations in the manifest ends up with
visuals sliding out from under the voice as soon as anyone edits a line. This
one cannot drift, because no duration is ever written down by a human.

The cost: you can't pin a scene to an exact length. If you need to hit 30.0s
exactly, adjust `speed` in the manifest, which is the knob TTS actually
respects.

### 2. Content-hash caching, not timestamps

`sha256(text|voice|speed)` names the wav. `sha256(the entire rendered HTML)`
names the png. So:

- Edit one narration line → one line re-spoken (~4s), everything else reused.
- Change the accent color in `CSS` → every frame's hash changes, all re-render,
  no audio touched.
- Nothing is ever stale, because the key *is* the content. No invalidation
  logic exists to get wrong.

First build: ~26s. Cached rebuild: ~19s, nearly all of it ffmpeg re-encoding.

### 3. HTML + headless Chrome as the renderer

Rejected Remotion (npm + React + bundler) and ffmpeg `drawtext` (unusable for
code) in favour of the browser that's already installed. Chrome gives real
typography, ligatures, border-radius, and radial gradients for free, and the
scene template is 60 lines of CSS anyone can edit.

The hard limit: **stills only.** No motion, no transitions, no animated code
diffs. That is the one thing worth switching to Remotion for, and the seam is
clean — swap `render.py`, keep stages 1 and 3 exactly as they are.

### 4. Captions are baked into the frame

The narration text is drawn into the PNG by the same CSS that draws the scene.
Zero ffmpeg subtitle work, and it is *structurally impossible* for a caption to
desync from its audio — they're the same image, cut to the same duration.

The tradeoff: captions appear a whole scene at a time, not word by word.
Word-level karaoke needs forced alignment:

```
pip install faster-whisper
wav → whisper word timestamps → per-word spans → animated .ass or per-frame HTML
```

That is the single biggest quality upgrade available and it's an afternoon of
work. It is deliberately not here because whisper isn't installed on this
machine.

### Per-scene clips, not global delay arithmetic

`assemble.py` builds one self-contained MP4 per scene, video and audio cut to
the identical length, then concatenates with `-c copy`. The alternative —
one long timeline with `adelay`/`amix` offsets — makes every scene's
correctness depend on every earlier scene's duration. Per-scene means a scene
is either right in isolation or it isn't; nothing can accumulate drift.

### 5. Avatar sync reuses stage 1's audio, doesn't precede it

`avatar.py` runs *after* `tts.py`, consuming its wav output — same "audio
drives timing" rule as everything else. Wav2Lip's own output duration is
determined by the audio it's given, so the avatar clip and the narration are
inherently the same length; nothing has to be trimmed to match afterward.

Chose **Wav2Lip** over SadTalker/LivePortrait/MuseTalk specifically because it
doesn't need CUDA and has no dlib build step (both are common install
failure points on macOS ARM). Its tradeoff: mouth-only motion on a frozen
photo, no head movement, no blinking. That is real "talking-photo" quality,
not "AI avatar" quality — the upgrade path is named in the omissions table
below, and it's a swap of `avatar.py`'s subprocess call, not a pipeline
redesign.

The face photo is never auto-sourced. `sync()` requires `avatar.face` to
already exist on disk — see the README's "Optional: lip-synced avatar"
section for why that line is deliberately not automated.

## Deliberate omissions

Marked with `ponytail:` comments in the source where they touch code.

| Not here | Add when |
|---|---|
| Word-level captions | You want retention on shorts. Needs whisper |
| Motion / transitions | A hard cut stops feeling intentional. Needs Remotion |
| Background music | You have a track. It's one `amix` with the music at −22 dBFS |
| B-roll / screen recording | The topic needs to show a real UI. `webapp-recorder` next door already drives Playwright and outputs narrated screencasts — its clips drop straight into stage 3 as extra scenes |
| YouTube upload | You're publishing more than occasionally. `videos.insert` costs 1600 of a 10,000/day quota → 6 uploads/day |
| Parallel stage 1/2 | Scene count goes past ~30 |
| Its own venv (tts.py) | The projects separate. Two constants in `tts.py` |
| Avatar head motion / blinking | Wav2Lip only moves the mouth, on a still photo. SadTalker/LivePortrait add head motion — much heavier install, GPU-shaped |
| Avatar ring / drop shadow | Purely cosmetic. One more `geq`-drawn circle behind the masked overlay in `assemble.py` |

## Known ceilings

- **macOS only** — hardcoded Chrome path.
- **Self-contained by default.** `make setup` builds this project's own venv
  and fetches its own kokoro weights into `models/`, so a fresh clone needs
  nothing beside it. `KOKORO_MODEL_DIR` points at an existing copy (e.g.
  webapp-recorder's `tts-models/`) when you'd rather not store them twice.
- **The syntax highlighter is three regex alternatives**, not a lexer. Comments,
  single-quoted strings, and a keyword list. It is correct on the cases that
  broke it once (URLs inside strings; spans corrupting each other) and
  `src/test_render.py` pins exactly those. Nested quotes or template literals
  will colour wrong — swap in Pygments if that ever matters.
- **The avatar pipeline runs on CPU, not Apple's MPS GPU backend.** Wav2Lip's
  own `inference.py` hardcodes `'cuda' if available else 'cpu'` — it predates
  MPS. Fine at a few seconds of audio per scene; would need patching that one
  line (and testing which ops MPS actually supports in this old codebase) if
  scene count or clip length grows a lot.
- **`.avatar-venv` is `--system-site-packages`**, deliberately, to reuse this
  machine's existing global torch/opencv (~2GB) instead of a second copy.
  Confirmed the global install (other projects' langchain/numpy pins
  included) is untouched — pip installs into a venv always land in the venv's
  own site-packages, never the parent's, even with that flag on.
- **`vendor/Wav2Lip/audio.py` is patched post-clone** (by `make avatar-setup`,
  via `sed`): the repo predates librosa 0.10, which made `filters.mel()`'s
  args keyword-only. Without the patch, every avatar clip fails with
  `TypeError: mel() takes 0 positional arguments but 2 were given`.
- **`--wav2lip_batch_size 8 --face_det_batch_size 4`** (default: 128/16) in
  `avatar.py` — this machine runs with ~90% of disk already committed and
  swaps heavily under memory pressure; the default batch size held an entire
  scene's frames in memory at once and briefly drove free disk under 300MB
  via swap-file growth (not a leak in this code — `vm.swapusage` confirmed
  it, and free space rebounded within a minute of the process exiting). Raise
  the batch sizes back up only on a machine with real headroom.
