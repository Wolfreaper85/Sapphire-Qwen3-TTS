# Sapphire-Qwen3-TTS

Local AI text-to-speech plugin for [Sapphire](https://github.com/SapphireAI) with voice cloning, voice design, and preset speakers. Uses [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) models from Alibaba/Qwen.

## Features

- **Voice Design** - Create voices from natural language descriptions (e.g. "a warm, gravelly male voice with a slow pace")
- **Voice Cloning** - Clone any voice from a 3-second audio sample
- **9 Preset Speakers** - Aiden, Dylan, Eric, Ono_anna, Ryan, Serena, Sohee, Uncle_fu, Vivian
- **Style Instructions** - Customize any preset with style directions (e.g. "speak cheerfully with a smile")
- **Voice Library** - Save, name, and manage your custom voices
- **Persona Integration** - Assign saved voices to Sapphire personas
- **10 Languages** - Auto, Chinese, English, Japanese, Korean, French, German, Spanish, Portuguese, Russian, Italian
- **Fully Self-Contained** - No core Sapphire file changes required

## Requirements

### Hardware
- **NVIDIA GPU** with 6+ GB VRAM (recommended 8+ GB)
- CUDA-capable driver installed

### Software
- **Python 3.10+** (3.11 recommended)
- **PyTorch with CUDA** - version depends on your GPU (see install guide below)
- **Sapphire** - the plugin runs inside Sapphire's plugin system
- **OS:** Windows 10+, Linux (Ubuntu 22.04+, Fedora, Arch), or macOS with NVIDIA eGPU

## Installation

### Quick Install (Recommended)

**Windows:** Double-click **`install.bat`**

**Linux / macOS:**
```bash
chmod +x install.sh
./install.sh
```

The installer auto-detects your GPU, installs the right PyTorch + CUDA version, installs all dependencies, and optionally installs the faster backend. Just follow the prompts.

### Manual Install

#### 1. Clone or Download

Copy the `qwen3-tts` folder into your Sapphire `plugins/` directory:

```
sapphire-dev/
  plugins/
    qwen3-tts/    <-- this plugin
      plugin.json
      provider.py
      server.py
      ...
```

#### 2. Install PyTorch (GPU-specific)

PyTorch must match your GPU generation. Pick the right command:

**RTX 5070 / 5080 / 5090 (Blackwell):**
```bash
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128
```

**RTX 4060 - 4090 (Ada Lovelace):**
```bash
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu126
```

**RTX 3060 - 3090 (Ampere):**
```bash
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124
```

> **Not sure which GPU you have?** Run `nvidia-smi` in a terminal - it shows your GPU model at the top.

#### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

This installs `qwen-tts`, `soundfile`, `numpy`, `psutil`, and `requests`.

#### 4. Enable the Plugin

1. Start Sapphire
2. Go to **Settings** > **Plugins**
3. Enable **Qwen3-TTS**
4. The TTS server will auto-launch in the background

#### 5. First Run (Model Download)

On first launch, models automatically download from HuggingFace. Which models depend on your Model Size setting:

**0.6B (default — recommended for most setups):**

| Model | Size | Purpose |
|-------|------|---------|
| `Qwen3-TTS-12Hz-0.6B-CustomVoice` | ~1.5 GB | Preset speakers + style instructions |
| `Qwen3-TTS-12Hz-0.6B-Base` | ~1.5 GB | Voice cloning from audio samples |

**1.7B (full quality):**

| Model | Size | Purpose |
|-------|------|---------|
| `Qwen3-TTS-12Hz-1.7B-CustomVoice` | ~4.3 GB | Preset speakers + style instructions |
| `Qwen3-TTS-12Hz-1.7B-VoiceDesign` | ~4.3 GB | Natural language voice descriptions (1.7B only) |
| `Qwen3-TTS-12Hz-1.7B-Base` | ~4.3 GB | Voice cloning from audio samples |

This is a one-time download per model size. Models are cached in your HuggingFace cache directory.

## Usage

### Voice Lab (Settings Panel)

After enabling the plugin, a **Qwen3-TTS** tab appears in Settings with 4 sub-tabs:

| Tab | What It Does |
|-----|-------------|
| **Design** | Describe a voice in natural language and generate speech |
| **Clone** | Upload or record a 3-second audio clip to clone a voice |
| **Custom** | Pick a preset speaker and add style instructions |
| **Library** | View, manage, and delete your saved voices |

### Quick Start

1. Go to **Settings > Qwen3-TTS**
2. Wait for the status bar to show the server is running (models load in ~30s)
3. Pick a tab (Design, Clone, or Custom)
4. Enter some text and click **Generate Preview**
5. If you like it, give it a name and click **Save Voice**
6. Go to your persona settings and select the saved voice

### Assigning Voices to Personas

Saved voices appear in the persona voice dropdown when Qwen3-TTS is set as the active TTS provider. Voice IDs use the format:
- `qwen3:preset:ryan` - Built-in preset speaker
- `qwen3:{profile_id}` - Your saved voice profile

## Plugin Settings

| Setting | Default | Description |
|---------|---------|-------------|
| Model Size | 0.6B | `0.6B` (lighter, less VRAM) or `1.7B` (full quality + voice design) |
| Server Port | 5013 | Port for the TTS subprocess server |
| Device | cuda:0 | GPU device (`cuda:0`, `cuda:1`, or `cpu`) |
| Models to Load | All | Which models to load at startup. Idle models auto-offload to CPU after the timeout. |
| Offload Timeout | 60 | Seconds of inactivity before an idle model moves from GPU to CPU. Set 0 to disable. |

## Model Sizes: 0.6B vs 1.7B

Qwen3-TTS comes in two sizes. Choose based on your VRAM budget.

| Feature | 0.6B (Light) | 1.7B (Full) |
|---------|-------------|-------------|
| VRAM usage | ~2-3 GB | ~6-8 GB |
| Custom Voice (presets + style) | Yes | Yes |
| Voice Cloning | Yes | Yes |
| Voice Design (natural language) | No | Yes |
| Best for | Daily use alongside LLMs | Higher quality, voice creation |

**Typical VRAM budgets:**
- **RTX 5070 Ti (16 GB):** 0.6B works great alongside LM Studio (~10 GB for LLM). 1.7B requires closing other GPU apps.
- **RTX 4090 / 5090 (24 GB):** 1.7B fits comfortably alongside most LLMs.
- **Dual GPU setups:** Run LLM on one GPU, Qwen3-TTS on the other (`device: cuda:1`).

## Voice Types & Compatibility

| Voice Type | Model Bound? | Works Across Sizes? | Storage |
|-----------|-------------|-------------------|---------|
| **Built-in Presets** (Ryan, Serena, etc.) | No | Yes | No files (hardcoded) |
| **Custom Voice** (preset + style instruction) | No | Yes | `voices/custom/` |
| **Voice Clone** (from audio sample) | **Yes** | **No** — 0.6B clones fail on 1.7B and vice versa | `voices/0.6B/` or `voices/1.7B/` |
| **Voice Design** (natural language description) | **Yes** | 1.7B only | `voices/1.7B/` |

Custom voices are cross-compatible because they only store a speaker name and text instruction — no model-specific tensors. Clone voices contain cached embeddings (`.pt` files) with different tensor dimensions per model size, so they're locked to the size they were created on.

## Pro Tip: Design on 1.7B, Clone to 0.6B

Voice Design is 1.7B-only, but you can create a voice with it and then port it to 0.6B for daily use:

1. **Free up VRAM** — Close LM Studio or other GPU apps temporarily
2. **Switch to 1.7B** in plugin settings (the server will restart and reload models)
3. **Voice Design tab** — Describe your ideal voice (e.g. "a deep, gravelly male voice with a slight Southern accent")
4. **Generate previews** until you find one you like
5. **Save the voice** (this saves the preview audio too)
6. **Switch back to 0.6B** in plugin settings
7. **Voice Clone tab** — Upload the saved preview audio as your reference clip
8. **Save the clone** — Now you have a portable 0.6B version

The 0.6B clone won't be identical to the 1.7B design, but it captures the core vocal characteristics. This workflow lets you use 1.7B as a "voice creation studio" and 0.6B as your daily driver.

## Important Notes

### Auto-Offload (VRAM Management)

All loaded models start on GPU. After 60 seconds of inactivity, unused models automatically move to CPU RAM to free GPU memory. When a request comes in for an offloaded model, it reloads to GPU in ~2-3 seconds.

In practice: if you're only chatting with personas using cloned voices, the Design and CustomVoice models offload automatically, leaving the full GPU for the Base (clone) model. When you open Voice Lab to create new voices, the needed models reload on demand.

### Voice Clone Prompt Caching

When you save a cloned voice, a `.pt` file is created containing the pre-computed voice fingerprint (speaker embedding + reference codes). This means:
- Persona TTS calls are **faster** (no re-encoding audio each time)
- Voice output is **more consistent** across different sentences
- The cache is created once at save time and reused forever
- If you delete a voice, the `.pt` cache is cleaned up automatically

### Model Size Mismatch Protection

If you try to use a 1.7B clone voice while the 0.6B server is running (or vice versa), the provider will **block the request** with a clear error rather than producing garbled audio. Custom voices and built-in presets are not affected — they work on any size.

## File Structure

```
qwen3-tts/
  install.bat          - One-click installer for Windows
  install.sh           - One-click installer for Linux / macOS
  install.py           - Installer logic (GPU detection, PyTorch, deps)
  plugin.json          - Plugin manifest
  provider.py          - TTS provider (auto-launches server)
  server.py            - Standalone HTTP server (subprocess)
  voice_manager.py     - Voice profile CRUD
  routes/
    api.py             - 11 API endpoints
  web/
    index.js           - Voice Lab settings UI
    main.js            - CSS loader
    voice-lab.css      - Styling
  voices/
    custom/            - Custom preset voices (cross-compatible)
      audio/           - Preview audio for custom voices
    0.6B/              - Clone & design voices for 0.6B model
      audio/           - Reference & preview audio
    1.7B/              - Clone & design voices for 1.7B model
      audio/           - Reference & preview audio
```

## Performance

Tested on RTX 5070 Ti (16 GB VRAM):

| Mode | Typical Generation Time |
|------|------------------------|
| CustomVoice (short sentence) | ~17 seconds |
| CustomVoice (with style instruction) | ~30 seconds |
| VoiceDesign (described voice) | ~29 seconds |

Output format: 24000 Hz, OGG/Opus

> **Tip:** Install `flash-attn` for faster generation (requires CUDA Toolkit SDK to compile - optional).

## Troubleshooting

**Server not starting?**
- Check that PyTorch CUDA is working: `python -c "import torch; print(torch.cuda.is_available())"`
- Check the server log at `logs/qwen3-tts.log` in your Sapphire directory

**Models not downloading?**
- Ensure you have internet access on first launch
- If using a portable HuggingFace cache, set `HF_HOME` environment variable to your cache path

**Out of VRAM?**
- Switch to the `0.6B` model size in plugin settings
- Close other GPU-intensive applications
- All 3 models load together (~3.9 GB VRAM each for 1.7B)

**Wrong GPU selected?**
- If you have multiple GPUs, change the Device setting to `cuda:1`

## Credits

- [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) by Alibaba/Qwen - Apache 2.0 License
- Built for [Sapphire AI](https://github.com/SapphireAI)

## License

MIT License - see [LICENSE](LICENSE) for details.
