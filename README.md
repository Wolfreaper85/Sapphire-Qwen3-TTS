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

## Installation

### 1. Clone or Download

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

### 2. Install PyTorch (GPU-specific)

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

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

This installs `qwen-tts`, `soundfile`, `numpy`, `psutil`, and `requests`.

### 4. Enable the Plugin

1. Start Sapphire
2. Go to **Settings** > **Plugins**
3. Enable **Qwen3-TTS**
4. The TTS server will auto-launch in the background

### 5. First Run (Model Download)

On first launch, three models will automatically download from HuggingFace (~13 GB total):

| Model | Size | Purpose |
|-------|------|---------|
| `Qwen3-TTS-12Hz-1.7B-CustomVoice` | ~4.3 GB | Preset speakers + style instructions |
| `Qwen3-TTS-12Hz-1.7B-VoiceDesign` | ~4.3 GB | Natural language voice descriptions |
| `Qwen3-TTS-12Hz-1.7B-Base` | ~4.3 GB | Voice cloning from audio samples |

This is a one-time download. Models are cached in your HuggingFace cache directory.

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
| Model Size | 1.7B | `1.7B` (full quality) or `0.6B` (lighter, less VRAM) |
| Server Port | 5013 | Port for the TTS subprocess server |
| Device | cuda:0 | GPU device (`cuda:0`, `cuda:1`, or `cpu`) |

## File Structure

```
qwen3-tts/
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
  voices/              - Saved voice profiles (runtime)
    audio/             - Reference audio files (runtime)
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
