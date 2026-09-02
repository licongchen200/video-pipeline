# kokoro-onnx has no Python 3.14 wheels yet, hence the pinned 3.13.
PYTHON ?= python3.13
PY := .venv/bin/python3
VIDEO ?= script.yaml

# One-time: the venv and the ~350MB kokoro model pair this project needs to
# run at all. If you already have webapp-recorder checked out next door, its
# tts-models/ holds the identical files — skip the download with:
#   KOKORO_MODEL_DIR=../webapp-recorder/tts-models make
setup:
	command -v $(PYTHON) >/dev/null || { echo "need $(PYTHON) — brew install python@3.13"; exit 1; }
	$(PYTHON) -m venv .venv
	$(PY) -m pip install --quiet --upgrade pip
	$(PY) -m pip install --quiet pyyaml soundfile 'git+https://github.com/thewh1teagle/kokoro-onnx.git@main'
	mkdir -p models
	curl -sL -o models/kokoro-v1.0.onnx \
		https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/kokoro-v1.0.onnx
	curl -sL -o models/voices-v1.0.bin \
		https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/voices-v1.0.bin
	@echo "ready — run \`make\`"

build:
	@test -x $(PY) || { echo "no .venv — run \`make setup\` first"; exit 1; }
	@$(PY) src/build.py $(VIDEO)

open: build
	@open out/*.mp4

draft:
	@test -n "$(TOPIC)" || { echo 'usage: make draft TOPIC="how to ..."'; exit 1; }
	@$(PY) src/write_script.py "$(TOPIC)" --seconds $(or $(SECONDS),30)

avatar-setup:
	git clone --depth 1 https://github.com/Rudrabha/Wav2Lip.git vendor/Wav2Lip
	python3.11 -m venv .avatar-venv --system-site-packages
	.avatar-venv/bin/pip install --quiet librosa numba resampy tqdm opencv-contrib-python
	mkdir -p vendor/Wav2Lip/checkpoints vendor/Wav2Lip/face_detection/detection/sfd
	curl -sL -o vendor/Wav2Lip/checkpoints/wav2lip_gan.pth \
		https://huggingface.co/Non-playing-Character/Wave2lip/resolve/main/wav2lip_gan.pth
	curl -sL -o vendor/Wav2Lip/face_detection/detection/sfd/s3fd.pth \
		https://www.adrianbulat.com/downloads/python-fan/s3fd-619a316812.pth
	# Wav2Lip predates librosa 0.10, which made filters.mel()'s args
	# keyword-only — patch the one positional call site.
	sed -i '' 's/librosa\.filters\.mel(hp\.sample_rate, hp\.n_fft, n_mels=hp\.num_mels,/librosa.filters.mel(sr=hp.sample_rate, n_fft=hp.n_fft, n_mels=hp.num_mels,/' \
		vendor/Wav2Lip/audio.py
	@echo "avatar pipeline ready — set avatar.face in script.yaml and avatar.enabled: true"

# SadTalker: much slower (~5s/frame) but far more convincing than Wav2Lip —
# full 3D-aware face render on MPS, not a pasted mouth patch. Every step
# below works around a real bug hit getting this running on Apple Silicon;
# see ARCHITECTURE.md for why each one is needed.
avatar-setup-sadtalker:
	git clone --depth 1 https://github.com/OpenTalker/SadTalker.git vendor/SadTalker
	python3.11 -m venv .sadtalker-venv --system-site-packages
	.sadtalker-venv/bin/pip install --quiet cython setuptools wheel
	.sadtalker-venv/bin/pip install --quiet --no-build-isolation basicsr==1.4.2
	.sadtalker-venv/bin/pip install --quiet face_alignment imageio-ffmpeg librosa \
		resampy kornia yacs facexlib gfpgan torchvision
	mkdir -p vendor/SadTalker/checkpoints
	curl -sL -o vendor/SadTalker/checkpoints/SadTalker_V0.0.2_256.safetensors \
		https://github.com/OpenTalker/SadTalker/releases/download/v0.0.2-rc/SadTalker_V0.0.2_256.safetensors
	curl -sL -o vendor/SadTalker/checkpoints/mapping_00109-model.pth.tar \
		https://github.com/OpenTalker/SadTalker/releases/download/v0.0.2-rc/mapping_00109-model.pth.tar
	curl -sL -o vendor/SadTalker/checkpoints/mapping_00229-model.pth.tar \
		https://github.com/OpenTalker/SadTalker/releases/download/v0.0.2-rc/mapping_00229-model.pth.tar
	curl -sL -o /tmp/BFM_Fitting.zip \
		https://github.com/Winfredy/SadTalker/releases/download/v0.0.2/BFM_Fitting.zip
	unzip -q -o /tmp/BFM_Fitting.zip -d vendor/SadTalker/checkpoints/ && rm /tmp/BFM_Fitting.zip
	rm -rf vendor/SadTalker/checkpoints/__MACOSX
	# BFM files actually belong in src/config/ (flat), not checkpoints/BFM_Fitting/
	# — that's where load_mats.py's dir_of_BFM_fitting param actually points.
	cp vendor/SadTalker/checkpoints/BFM_Fitting/* vendor/SadTalker/src/config/
	python3.11 src/patch_sadtalker.py
	@echo "SadTalker ready — set avatar.engine: sadtalker in script.yaml"

# Pure logic — no models, no venv needed, so any python3 will do.
test:
	@cd src && python3 test_render.py

clean:
	rm -rf build out

.PHONY: setup build open draft test clean avatar-setup avatar-setup-sadtalker
