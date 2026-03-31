"""Qwen3-TTS subprocess server — isolates GPU model from main Sapphire process.

Modeled after core/tts/tts_server.py (Kokoro). Runs as a standalone HTTP server
that loads Qwen3-TTS models and exposes generation endpoints.

Endpoints:
    GET  /health              — Liveness check + model/memory info
    POST /generate/custom     — Generate with preset speaker + optional instruction
    POST /generate/design     — Generate with natural language voice description
    POST /generate/clone      — Generate by cloning a reference audio
"""
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
import faulthandler
import json
import time
import os
import sys
import uuid
import logging
import threading
import tempfile
import base64
import io

import numpy as np
import soundfile as sf

faulthandler.enable()

# --- Path setup ---
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(script_dir))
sys.path.insert(0, project_root)

# --- HuggingFace cache: respect Sapphire's HF_HOME (set by Start Sapphire.bat) ---
# If HF_HOME isn't set, default to W:\Sapphire\.hf_cache if it exists (portable install)
if not os.environ.get('HF_HOME'):
    portable_cache = os.path.join(os.path.dirname(project_root), '.hf_cache')
    if os.path.isdir(portable_cache):
        os.environ['HF_HOME'] = portable_cache

# --- Logging ---
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- Configuration ---
HOST = os.environ.get('QWEN3_TTS_HOST', '0.0.0.0')
PORT = int(os.environ.get('QWEN3_TTS_PORT', '5013'))
DEVICE = os.environ.get('QWEN3_TTS_DEVICE', 'cuda:0')
MODEL_SIZE = os.environ.get('QWEN3_TTS_MODEL_SIZE', '1.7B')
# Comma-separated list of models to load: "custom_voice,voice_design,base" or "all"
LOAD_MODELS = os.environ.get('QWEN3_TTS_LOAD_MODELS', 'all').lower().strip()

# Auto-offload idle models after this many seconds (0 = never offload)
OFFLOAD_TIMEOUT = int(os.environ.get('QWEN3_TTS_OFFLOAD_TIMEOUT', '60'))

# --- Constants ---
AUDIO_SAMPLE_RATE = 24000  # Qwen3-TTS output rate (will be set from model)
MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10MB max (for clone audio uploads)
MAX_NEW_TOKENS = 2048

# --- Memory management ---
MAX_REQUESTS = 500
request_count = 0
request_count_lock = threading.Lock()
generation_lock = threading.Lock()

# --- Model storage ---
# Models on GPU (active)
models = {
    'custom_voice': None,
    'voice_design': None,
    'base': None,
}
# Models offloaded to CPU (idle)
models_cpu = {
    'custom_voice': None,
    'voice_design': None,
    'base': None,
}
# Track last usage time per model
model_last_used = {
    'custom_voice': 0.0,
    'voice_design': 0.0,
    'base': 0.0,
}


def get_temp_dir():
    if sys.platform == 'linux':
        shm = '/dev/shm'
        if os.path.exists(shm) and os.access(shm, os.W_OK):
            return shm
    return tempfile.gettempdir()


TEMP_DIR = get_temp_dir()


def _should_load(model_key):
    """Check if a model should be loaded based on LOAD_MODELS config."""
    if LOAD_MODELS == 'all':
        return True
    requested = [m.strip() for m in LOAD_MODELS.split(',')]
    return model_key in requested


def _get_attn_impl():
    """Return 'flash_attention_2' if flash-attn is installed, else None (uses default)."""
    try:
        import flash_attn  # noqa: F401
        logger.info("flash-attn detected — using flash_attention_2")
        return "flash_attention_2"
    except ImportError:
        logger.warning("flash-attn not installed — using default attention (slower)")
        return None


def _try_faster_backend():
    """Check if faster-qwen3-tts is available."""
    try:
        from faster_qwen3_tts import FasterQwen3TTS
        logger.info("faster-qwen3-tts detected — using CUDA graph acceleration (5-10x speedup)")
        return True
    except ImportError:
        logger.info("faster-qwen3-tts not installed — using standard qwen_tts backend")
        return False


USE_FASTER = False  # Set at load time


def load_models():
    """Load Qwen3-TTS models. Only loads models specified by LOAD_MODELS config."""
    global AUDIO_SAMPLE_RATE, USE_FASTER

    try:
        import torch
    except ImportError as e:
        logger.error(f"Failed to import torch: {e}")
        sys.exit(1)

    USE_FASTER = _try_faster_backend()

    dtype = torch.bfloat16
    attn_impl = _get_attn_impl()

    # CUDA graphs are incompatible with Flash Attention 2 — the graph capture
    # fails with "Offset increment outside graph capture encountered unexpectedly".
    # Force SDPA when using the faster backend.
    if USE_FASTER and attn_impl == "flash_attention_2":
        logger.info("Overriding flash_attention_2 → sdpa (required for CUDA graph capture)")
        attn_impl = "sdpa"

    logger.info(f"Model loading config: LOAD_MODELS={LOAD_MODELS}")

    if USE_FASTER:
        _load_models_faster(dtype, attn_impl)
    else:
        _load_models_standard(dtype, attn_impl)

    loaded = [k for k, v in models.items() if v is not None]
    logger.info(f"Models loaded: {', '.join(loaded) or 'none'}")
    if USE_FASTER:
        logger.info("Backend: faster-qwen3-tts (CUDA graphs + static KV cache)")
    else:
        logger.info("Backend: standard qwen_tts")

    # Mark all loaded models as recently used
    now = time.time()
    for k in loaded:
        model_last_used[k] = now

    # Start the offload timer (only for standard backend — faster backend doesn't support CPU offload)
    if OFFLOAD_TIMEOUT > 0 and not USE_FASTER:
        _start_offload_timer()


def _load_models_faster(dtype, attn_impl):
    """Load models using faster-qwen3-tts with CUDA graph acceleration."""
    from faster_qwen3_tts import FasterQwen3TTS

    attn_kwarg = attn_impl if attn_impl else "sdpa"

    # CustomVoice model
    if _should_load('custom_voice'):
        logger.info(f"Loading CustomVoice model ({MODEL_SIZE}) with CUDA graphs...")
        try:
            models['custom_voice'] = FasterQwen3TTS.from_pretrained(
                f"Qwen/Qwen3-TTS-12Hz-{MODEL_SIZE}-CustomVoice",
                device=DEVICE, dtype=dtype, attn_implementation=attn_kwarg,
            )
            logger.info("CustomVoice model loaded (faster)")
        except Exception as e:
            logger.error(f"Failed to load CustomVoice model (faster): {e}", exc_info=True)
    else:
        logger.info("Skipping CustomVoice model (not in LOAD_MODELS)")

    # VoiceDesign model (1.7B only)
    if _should_load('voice_design'):
        if MODEL_SIZE == '1.7B':
            logger.info("Loading VoiceDesign model (1.7B) with CUDA graphs...")
            try:
                models['voice_design'] = FasterQwen3TTS.from_pretrained(
                    "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
                    device=DEVICE, dtype=dtype, attn_implementation=attn_kwarg,
                )
                logger.info("VoiceDesign model loaded (faster)")
            except Exception as e:
                logger.error(f"Failed to load VoiceDesign model (faster): {e}", exc_info=True)
        else:
            logger.info("Skipping VoiceDesign model (requires 1.7B)")
    else:
        logger.info("Skipping VoiceDesign model (not in LOAD_MODELS)")

    # Base model (voice cloning)
    if _should_load('base'):
        logger.info(f"Loading Base model ({MODEL_SIZE}) with CUDA graphs...")
        try:
            models['base'] = FasterQwen3TTS.from_pretrained(
                f"Qwen/Qwen3-TTS-12Hz-{MODEL_SIZE}-Base",
                device=DEVICE, dtype=dtype, attn_implementation=attn_kwarg,
            )
            logger.info("Base (clone) model loaded (faster)")
        except Exception as e:
            logger.error(f"Failed to load Base model (faster): {e}", exc_info=True)
    else:
        logger.info("Skipping Base model (not in LOAD_MODELS)")


def _load_models_standard(dtype, attn_impl):
    """Load models using standard qwen_tts backend (fallback)."""
    try:
        from qwen_tts import Qwen3TTSModel
    except ImportError as e:
        logger.error(f"Failed to import qwen_tts: {e}")
        logger.error("Install with: pip install -U qwen-tts")
        sys.exit(1)

    attn_kwargs = {"attn_implementation": attn_impl} if attn_impl else {}

    # CustomVoice model (preset speakers + instruction control)
    if _should_load('custom_voice'):
        logger.info(f"Loading CustomVoice model ({MODEL_SIZE})...")
        try:
            models['custom_voice'] = Qwen3TTSModel.from_pretrained(
                f"Qwen/Qwen3-TTS-12Hz-{MODEL_SIZE}-CustomVoice",
                device_map=DEVICE, torch_dtype=dtype, **attn_kwargs,
            )
            logger.info("CustomVoice model loaded")
        except Exception as e:
            logger.error(f"Failed to load CustomVoice model: {e}")
    else:
        logger.info("Skipping CustomVoice model (not in LOAD_MODELS)")

    # VoiceDesign model (1.7B only — natural language voice descriptions)
    if _should_load('voice_design'):
        if MODEL_SIZE == '1.7B':
            logger.info("Loading VoiceDesign model (1.7B only)...")
            try:
                models['voice_design'] = Qwen3TTSModel.from_pretrained(
                    "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
                    device_map=DEVICE, torch_dtype=dtype, **attn_kwargs,
                )
                logger.info("VoiceDesign model loaded")
            except Exception as e:
                logger.error(f"Failed to load VoiceDesign model: {e}")
        else:
            logger.info("Skipping VoiceDesign model (requires 1.7B)")
    else:
        logger.info("Skipping VoiceDesign model (not in LOAD_MODELS)")

    # Base model (voice cloning)
    if _should_load('base'):
        logger.info(f"Loading Base model ({MODEL_SIZE}) for voice cloning...")
        try:
            models['base'] = Qwen3TTSModel.from_pretrained(
                f"Qwen/Qwen3-TTS-12Hz-{MODEL_SIZE}-Base",
                device_map=DEVICE, torch_dtype=dtype, **attn_kwargs,
            )
            logger.info("Base (clone) model loaded")
        except Exception as e:
            logger.error(f"Failed to load Base model: {e}")
    else:
        logger.info("Skipping Base model (not in LOAD_MODELS)")

    # Start the offload timer
    if OFFLOAD_TIMEOUT > 0:
        _start_offload_timer()


def _offload_model(key):
    """Move a model from GPU to CPU to free VRAM."""
    import torch
    model = models.get(key)
    if model is None:
        return
    try:
        model.model.to('cpu')
        torch.cuda.empty_cache()
        models_cpu[key] = model
        models[key] = None
        logger.info(f"Offloaded {key} to CPU (idle > {OFFLOAD_TIMEOUT}s)")
    except Exception as e:
        logger.error(f"Failed to offload {key}: {e}")


def _reload_model(key):
    """Move a model from CPU back to GPU."""
    import torch
    model = models_cpu.get(key)
    if model is None:
        return False
    try:
        logger.info(f"Reloading {key} to {DEVICE}...")
        model.model.to(DEVICE)
        models[key] = model
        models_cpu[key] = None
        model_last_used[key] = time.time()
        logger.info(f"Reloaded {key} to GPU")
        return True
    except Exception as e:
        logger.error(f"Failed to reload {key}: {e}")
        return False


def _get_model(key):
    """Get a model, reloading from CPU if it was offloaded."""
    if models.get(key) is not None:
        model_last_used[key] = time.time()
        return models[key]
    # Try to reload from CPU
    if models_cpu.get(key) is not None:
        with generation_lock:
            # Double-check inside lock
            if models.get(key) is not None:
                model_last_used[key] = time.time()
                return models[key]
            if _reload_model(key):
                return models[key]
    return None


def _offload_check():
    """Check for idle models and offload them. Runs periodically."""
    now = time.time()
    for key in list(models.keys()):
        if models[key] is None:
            continue
        idle_time = now - model_last_used.get(key, 0)
        if idle_time > OFFLOAD_TIMEOUT:
            with generation_lock:
                # Re-check after acquiring lock
                if models[key] is not None and (time.time() - model_last_used.get(key, 0)) > OFFLOAD_TIMEOUT:
                    _offload_model(key)


_offload_timer = None

def _start_offload_timer():
    """Start a repeating timer that checks for idle models."""
    global _offload_timer

    def _tick():
        global _offload_timer
        try:
            _offload_check()
        except Exception as e:
            logger.error(f"Offload check error: {e}")
        _offload_timer = threading.Timer(15, _tick)
        _offload_timer.daemon = True
        _offload_timer.start()

    _offload_timer = threading.Timer(15, _tick)
    _offload_timer.daemon = True
    _offload_timer.start()
    logger.info(f"Offload timer started (timeout={OFFLOAD_TIMEOUT}s, check every 15s)")


def _json_response(handler, data, status=200):
    body = json.dumps(data).encode()
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json')
    handler.send_header('Content-Length', str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _audio_response(handler, audio_np, sample_rate):
    """Encode numpy audio to OGG/Opus and send as response."""
    file_uuid = uuid.uuid4().hex
    file_path = os.path.join(TEMP_DIR, f'qwen3_{int(time.time())}_{file_uuid}.ogg')

    try:
        sf.write(file_path, audio_np, sample_rate, format='OGG', subtype='OPUS')

        with open(file_path, 'rb') as f:
            data = f.read()

        handler.send_response(200)
        handler.send_header('Content-Type', 'audio/ogg')
        handler.send_header('Content-Length', str(len(data)))
        handler.send_header('Content-Disposition', 'attachment; filename="qwen3_output.ogg"')
        handler.end_headers()
        handler.wfile.write(data)
    finally:
        try:
            os.remove(file_path)
        except Exception:
            pass


def _read_json_body(handler):
    """Read and parse JSON from request body."""
    content_length = int(handler.headers.get('Content-Length', 0))
    if content_length > MAX_CONTENT_LENGTH:
        return None, "Request body too large"
    body = handler.rfile.read(content_length)
    try:
        return json.loads(body), None
    except (json.JSONDecodeError, ValueError):
        return None, "Invalid JSON body"


def _ensure_mono_float32(wav):
    """Convert audio to mono float32. Fixes qwen_tts tuple assignment bug with stereo input."""
    wav = wav.astype(np.float32)
    if wav.ndim > 1:
        wav = np.mean(wav, axis=-1).astype(np.float32)
    return wav


def _resolve_ref_audio_path(data):
    """Resolve reference audio to a file path (for faster backend).

    Handles base64 by saving to temp file, or returns existing path.
    Returns file path string or None.
    """
    ref_audio = data.get('ref_audio')
    if not ref_audio:
        return None

    # Base64 encoded audio — save to temp file
    if isinstance(ref_audio, str) and len(ref_audio) > 200:
        try:
            audio_bytes = base64.b64decode(ref_audio)
            temp_path = os.path.join(TEMP_DIR, f'ref_{uuid.uuid4().hex[:8]}.wav')
            with open(temp_path, 'wb') as f:
                f.write(audio_bytes)
            return temp_path
        except Exception:
            return None

    # File path (from voice manager audio dir)
    if isinstance(ref_audio, str):
        audio_dir = os.path.join(script_dir, 'voices', 'audio')
        audio_path = os.path.join(audio_dir, ref_audio)
        if os.path.exists(audio_path):
            return audio_path

    return None


def _decode_ref_audio(data):
    """Decode reference audio from base64 or file path. Returns (wav_np, sr) tuple."""
    ref_audio = data.get('ref_audio')
    if not ref_audio:
        return None, None

    # Base64 encoded audio
    if isinstance(ref_audio, str) and len(ref_audio) > 200:
        try:
            audio_bytes = base64.b64decode(ref_audio)
            wav, sr = sf.read(io.BytesIO(audio_bytes))
            wav = _ensure_mono_float32(wav)
            return (wav, sr), None
        except Exception as e:
            return None, f"Failed to decode base64 audio: {e}"

    # File path (from voice manager audio dir)
    if isinstance(ref_audio, str):
        audio_dir = os.path.join(script_dir, 'voices', 'audio')
        audio_path = os.path.join(audio_dir, ref_audio)
        if os.path.exists(audio_path):
            try:
                wav, sr = sf.read(audio_path)
                wav = _ensure_mono_float32(wav)
                return (wav, sr), None
            except Exception as e:
                return None, f"Failed to read audio file: {e}"
        return None, f"Audio file not found: {ref_audio}"

    return None, "Invalid ref_audio format"


class Qwen3TTSHandler(BaseHTTPRequestHandler):
    """HTTP handler for Qwen3-TTS generation requests."""

    def log_message(self, format, *args):
        pass  # Suppress default logging

    def do_GET(self):
        if self.path == '/health':
            self._handle_health()
        else:
            self.send_error(404)

    def do_POST(self):
        routes = {
            '/generate/custom': self._handle_custom_voice,
            '/generate/design': self._handle_voice_design,
            '/generate/clone': self._handle_voice_clone,
            '/create-prompt': self._handle_create_prompt,
        }
        handler = routes.get(self.path)
        if handler:
            handler()
        else:
            self.send_error(404)

    def _handle_health(self):
        try:
            import psutil
            mem_gb = psutil.Process(os.getpid()).memory_info().rss / (1024**3)
        except Exception:
            mem_gb = -1

        # GPU VRAM usage
        gpu_info = {}
        try:
            import torch
            if torch.cuda.is_available():
                gpu_info['vram_allocated_gb'] = round(torch.cuda.memory_allocated() / (1024**3), 2)
                gpu_info['vram_reserved_gb'] = round(torch.cuda.memory_reserved() / (1024**3), 2)
                total = torch.cuda.get_device_properties(0).total_mem
                gpu_info['vram_total_gb'] = round(total / (1024**3), 2)
        except Exception:
            pass

        model_status = {}
        for k in models:
            if models[k] is not None:
                status = 'gpu'
                # Check if Accelerate split layers across devices
                try:
                    dmap = getattr(models[k].model, 'hf_device_map', None)
                    if dmap:
                        devices_used = set(str(v) for v in dmap.values())
                        if len(devices_used) > 1 or 'cpu' in devices_used:
                            status = f'split:{",".join(sorted(devices_used))}'
                except Exception:
                    pass
                model_status[k] = status
            elif models_cpu[k] is not None:
                model_status[k] = 'cpu'
            else:
                model_status[k] = 'not_loaded'

        _json_response(self, {
            'status': 'ok',
            'models': {k: v is not None for k, v in models.items()},
            'model_status': model_status,
            'offload_timeout': OFFLOAD_TIMEOUT,
            'model_size': MODEL_SIZE,
            'device': DEVICE,
            'backend': 'faster-qwen3-tts' if USE_FASTER else 'standard',
            'requests': request_count,
            'memory_gb': round(mem_gb, 2),
            'gpu': gpu_info,
        })

    def _handle_custom_voice(self):
        """Generate with preset speaker + optional style instruction."""
        global request_count
        model = _get_model('custom_voice')
        if not model:
            _json_response(self, {'error': 'CustomVoice model not loaded'}, 503)
            return

        data, err = _read_json_body(self)
        if err:
            _json_response(self, {'error': err}, 400)
            return

        text = (data.get('text') or '').strip()
        if not text:
            _json_response(self, {'error': 'No text provided'}, 400)
            return

        speaker = data.get('speaker', 'ryan').lower().replace(' ', '_')
        instruct = (data.get('instruct') or '').strip() or None
        language = data.get('language', 'Auto')

        with request_count_lock:
            request_count += 1

        t0 = time.time()
        try:
            with generation_lock:
                result = model.generate_custom_voice(
                    text=text,
                    language=language,
                    speaker=speaker,
                    instruct=instruct,
                    non_streaming_mode=True,
                    max_new_tokens=MAX_NEW_TOKENS,
                )
                model_last_used['custom_voice'] = time.time()

            wavs, sr = result
            elapsed = time.time() - t0
            logger.info(f"CustomVoice generated in {elapsed:.2f}s (speaker={speaker}, backend={'faster' if USE_FASTER else 'standard'})")
            _audio_response(self, wavs[0] if isinstance(wavs, list) else wavs, sr)
        except Exception as e:
            logger.error(f"CustomVoice generation failed: {e}", exc_info=True)
            _json_response(self, {'error': str(e)}, 500)

    def _handle_voice_design(self):
        """Generate with natural language voice description."""
        global request_count
        model = _get_model('voice_design')
        if not model:
            _json_response(self, {'error': 'VoiceDesign model not loaded (requires 1.7B)'}, 503)
            return

        data, err = _read_json_body(self)
        if err:
            _json_response(self, {'error': err}, 400)
            return

        text = (data.get('text') or '').strip()
        if not text:
            _json_response(self, {'error': 'No text provided'}, 400)
            return

        instruct = (data.get('instruct') or '').strip()
        if not instruct:
            _json_response(self, {'error': 'No voice description provided'}, 400)
            return

        language = data.get('language', 'Auto')

        with request_count_lock:
            request_count += 1

        t0 = time.time()
        try:
            with generation_lock:
                result = model.generate_voice_design(
                    text=text,
                    language=language,
                    instruct=instruct,
                    non_streaming_mode=True,
                    max_new_tokens=MAX_NEW_TOKENS,
                )
                model_last_used['voice_design'] = time.time()

            wavs, sr = result
            elapsed = time.time() - t0
            logger.info(f"VoiceDesign generated in {elapsed:.2f}s (backend={'faster' if USE_FASTER else 'standard'})")
            _audio_response(self, wavs[0] if isinstance(wavs, list) else wavs, sr)
        except Exception as e:
            logger.error(f"VoiceDesign generation failed: {e}", exc_info=True)
            _json_response(self, {'error': str(e)}, 500)

    def _handle_create_prompt(self):
        """Pre-compute voice clone prompt and save as .pt file for reuse."""
        model = _get_model('base')
        if not model:
            _json_response(self, {'error': 'Base (clone) model not loaded'}, 503)
            return

        data, err = _read_json_body(self)
        if err:
            _json_response(self, {'error': err}, 400)
            return

        ref_audio_tuple, audio_err = _decode_ref_audio(data)
        if audio_err:
            _json_response(self, {'error': audio_err}, 400)
            return
        if ref_audio_tuple is None:
            _json_response(self, {'error': 'No reference audio provided'}, 400)
            return

        ref_text = (data.get('ref_text') or '').strip() or None
        x_vector_only = data.get('x_vector_only', False)
        save_path = data.get('save_path', '')

        if not save_path:
            _json_response(self, {'error': 'save_path is required'}, 400)
            return

        t0 = time.time()
        try:
            import torch
            from dataclasses import asdict

            with generation_lock:
                items = model.create_voice_clone_prompt(
                    ref_audio=ref_audio_tuple,
                    ref_text=ref_text,
                    x_vector_only_mode=bool(x_vector_only),
                )

            payload = {
                "items": [asdict(it) for it in items],
                "model_size": MODEL_SIZE,  # Tag so mismatched caches are rejected
            }

            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            torch.save(payload, save_path)

            elapsed = time.time() - t0
            logger.info(f"Voice clone prompt created in {elapsed:.2f}s -> {save_path}")
            _json_response(self, {'status': 'ok', 'path': save_path})
        except Exception as e:
            logger.error(f"Create voice clone prompt failed: {e}")
            _json_response(self, {'error': str(e)}, 500)

    def _handle_voice_clone(self):
        """Generate by cloning — uses cached prompt (.pt) if available, otherwise ref audio."""
        global request_count
        model = _get_model('base')
        if not model:
            _json_response(self, {'error': 'Base (clone) model not loaded'}, 503)
            return

        data, err = _read_json_body(self)
        if err:
            _json_response(self, {'error': err}, 400)
            return

        text = (data.get('text') or '').strip()
        if not text:
            _json_response(self, {'error': 'No text provided'}, 400)
            return

        language = data.get('language', 'Auto')
        prompt_path = data.get('prompt_path', '')

        with request_count_lock:
            request_count += 1

        t0 = time.time()
        try:
            # --- Cached prompt path (fast, consistent) ---
            if prompt_path and os.path.exists(prompt_path):
                import torch
                from qwen_tts.inference.qwen3_tts_model import VoiceClonePromptItem

                payload = torch.load(prompt_path, map_location="cpu", weights_only=True)

                # Validate that cached prompt matches current model size.
                # 1.7B uses 2048-dim speaker embeddings, 0.6B uses 1024-dim.
                # A mismatch causes "Sizes of tensors must match" errors.
                cache_model_size = payload.get("model_size", None)
                if cache_model_size and cache_model_size != MODEL_SIZE:
                    logger.warning(
                        f"Cached prompt was created with {cache_model_size} but server "
                        f"is running {MODEL_SIZE} — ignoring cache, using raw ref audio"
                    )
                    prompt_path = None  # fall through to raw ref audio path below

            if prompt_path and os.path.exists(prompt_path):
                import torch
                from qwen_tts.inference.qwen3_tts_model import VoiceClonePromptItem

                if 'payload' not in locals():
                    payload = torch.load(prompt_path, map_location="cpu", weights_only=True)
                items_raw = payload.get("items", [])
                items = []
                for d in items_raw:
                    ref_code = d.get("ref_code", None)
                    if ref_code is not None and not torch.is_tensor(ref_code):
                        ref_code = torch.tensor(ref_code)
                    ref_spk = d.get("ref_spk_embedding", None)
                    if ref_spk is not None and not torch.is_tensor(ref_spk):
                        ref_spk = torch.tensor(ref_spk)
                    items.append(VoiceClonePromptItem(
                        ref_code=ref_code,
                        ref_spk_embedding=ref_spk,
                        x_vector_only_mode=bool(d.get("x_vector_only_mode", False)),
                        icl_mode=bool(d.get("icl_mode", True)),
                        ref_text=d.get("ref_text", None),
                    ))

                with generation_lock:
                    result = model.generate_voice_clone(
                        text=text,
                        language=language,
                        voice_clone_prompt=items,
                        non_streaming_mode=True if not USE_FASTER else False,
                        max_new_tokens=MAX_NEW_TOKENS,
                    )
                    model_last_used['base'] = time.time()

                wavs, sr = result
                elapsed = time.time() - t0
                logger.info(f"VoiceClone (cached prompt) generated in {elapsed:.2f}s (backend={'faster' if USE_FASTER else 'standard'})")
                _audio_response(self, wavs[0] if isinstance(wavs, list) else wavs, sr)
                return

            # --- Fallback: raw ref audio (preview mode) ---
            ref_text = (data.get('ref_text') or '').strip() or None
            x_vector_only = data.get('x_vector_only', False)

            if USE_FASTER:
                # Faster backend takes ref_audio as a file path string
                ref_audio_path = _resolve_ref_audio_path(data)
                if not ref_audio_path:
                    _json_response(self, {'error': 'No reference audio or cached prompt provided'}, 400)
                    return

                with generation_lock:
                    result = model.generate_voice_clone(
                        text=text,
                        language=language,
                        ref_audio=ref_audio_path,
                        ref_text=ref_text or '',
                        xvec_only=x_vector_only,
                        non_streaming_mode=False,
                        max_new_tokens=MAX_NEW_TOKENS,
                    )
                    model_last_used['base'] = time.time()
                wavs, sr = result
            else:
                # Standard backend takes ref_audio as (wav_np, sr) tuple
                ref_audio_tuple, audio_err = _decode_ref_audio(data)
                if audio_err:
                    _json_response(self, {'error': audio_err}, 400)
                    return
                if ref_audio_tuple is None:
                    _json_response(self, {'error': 'No reference audio or cached prompt provided'}, 400)
                    return

                with generation_lock:
                    wavs, sr = model.generate_voice_clone(
                        text=text,
                        language=language,
                        ref_audio=ref_audio_tuple,
                        ref_text=ref_text,
                        x_vector_only_mode=x_vector_only,
                        non_streaming_mode=True,
                        max_new_tokens=MAX_NEW_TOKENS,
                    )
                    model_last_used['base'] = time.time()

            elapsed = time.time() - t0
            logger.info(f"VoiceClone (raw ref) generated in {elapsed:.2f}s (backend={'faster' if USE_FASTER else 'standard'})")
            _audio_response(self, wavs[0] if isinstance(wavs, list) else wavs, sr)
        except Exception as e:
            logger.error(f"VoiceClone generation failed: {e}")
            _json_response(self, {'error': str(e)}, 500)


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def main():
    logger.info(f"Starting Qwen3-TTS server on {HOST}:{PORT}")
    logger.info(f"Model size: {MODEL_SIZE}, Device: {DEVICE}")

    load_models()

    os.makedirs(TEMP_DIR, exist_ok=True)
    server = ThreadedHTTPServer((HOST, PORT), Qwen3TTSHandler)

    logger.info(f"Qwen3-TTS server ready on {HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Qwen3-TTS server shutting down")
        server.shutdown()


if __name__ == "__main__":
    main()
