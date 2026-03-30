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
models = {
    'custom_voice': None,
    'voice_design': None,
    'base': None,
}


def get_temp_dir():
    if sys.platform == 'linux':
        shm = '/dev/shm'
        if os.path.exists(shm) and os.access(shm, os.W_OK):
            return shm
    return tempfile.gettempdir()


TEMP_DIR = get_temp_dir()


def load_models():
    """Load Qwen3-TTS models. Called once at startup."""
    global AUDIO_SAMPLE_RATE

    try:
        import torch
        from qwen_tts import Qwen3TTSModel
    except ImportError as e:
        logger.error(f"Failed to import qwen_tts: {e}")
        logger.error("Install with: pip install -U qwen-tts")
        sys.exit(1)

    dtype = torch.bfloat16

    # CustomVoice model (preset speakers + instruction control)
    logger.info(f"Loading CustomVoice model ({MODEL_SIZE})...")
    try:
        models['custom_voice'] = Qwen3TTSModel.from_pretrained(
            f"Qwen/Qwen3-TTS-12Hz-{MODEL_SIZE}-CustomVoice",
            device_map=DEVICE, torch_dtype=dtype
        )
        logger.info("CustomVoice model loaded")
    except Exception as e:
        logger.error(f"Failed to load CustomVoice model: {e}")

    # VoiceDesign model (1.7B only — natural language voice descriptions)
    if MODEL_SIZE == '1.7B':
        logger.info("Loading VoiceDesign model (1.7B only)...")
        try:
            models['voice_design'] = Qwen3TTSModel.from_pretrained(
                "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
                device_map=DEVICE, torch_dtype=dtype
            )
            logger.info("VoiceDesign model loaded")
        except Exception as e:
            logger.error(f"Failed to load VoiceDesign model: {e}")
    else:
        logger.info("Skipping VoiceDesign model (requires 1.7B)")

    # Base model (voice cloning)
    logger.info(f"Loading Base model ({MODEL_SIZE}) for voice cloning...")
    try:
        models['base'] = Qwen3TTSModel.from_pretrained(
            f"Qwen/Qwen3-TTS-12Hz-{MODEL_SIZE}-Base",
            device_map=DEVICE, torch_dtype=dtype
        )
        logger.info("Base (clone) model loaded")
    except Exception as e:
        logger.error(f"Failed to load Base model: {e}")

    logger.info("All available models loaded successfully")


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
            return (wav.astype(np.float32), sr), None
        except Exception as e:
            return None, f"Failed to decode base64 audio: {e}"

    # File path (from voice manager audio dir)
    if isinstance(ref_audio, str):
        audio_dir = os.path.join(script_dir, 'voices', 'audio')
        audio_path = os.path.join(audio_dir, ref_audio)
        if os.path.exists(audio_path):
            try:
                wav, sr = sf.read(audio_path)
                return (wav.astype(np.float32), sr), None
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

        _json_response(self, {
            'status': 'ok',
            'models': {k: v is not None for k, v in models.items()},
            'model_size': MODEL_SIZE,
            'device': DEVICE,
            'requests': request_count,
            'memory_gb': round(mem_gb, 2),
        })

    def _handle_custom_voice(self):
        """Generate with preset speaker + optional style instruction."""
        global request_count
        model = models.get('custom_voice')
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
                wavs, sr = model.generate_custom_voice(
                    text=text,
                    language=language,
                    speaker=speaker,
                    instruct=instruct,
                    non_streaming_mode=True,
                    max_new_tokens=MAX_NEW_TOKENS,
                )
            elapsed = time.time() - t0
            logger.info(f"CustomVoice generated in {elapsed:.2f}s (speaker={speaker})")
            _audio_response(self, wavs[0], sr)
        except Exception as e:
            logger.error(f"CustomVoice generation failed: {e}")
            _json_response(self, {'error': str(e)}, 500)

    def _handle_voice_design(self):
        """Generate with natural language voice description."""
        global request_count
        model = models.get('voice_design')
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
                wavs, sr = model.generate_voice_design(
                    text=text,
                    language=language,
                    instruct=instruct,
                    non_streaming_mode=True,
                    max_new_tokens=MAX_NEW_TOKENS,
                )
            elapsed = time.time() - t0
            logger.info(f"VoiceDesign generated in {elapsed:.2f}s")
            _audio_response(self, wavs[0], sr)
        except Exception as e:
            logger.error(f"VoiceDesign generation failed: {e}")
            _json_response(self, {'error': str(e)}, 500)

    def _handle_voice_clone(self):
        """Generate by cloning from reference audio."""
        global request_count
        model = models.get('base')
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

        ref_audio_tuple, audio_err = _decode_ref_audio(data)
        if audio_err:
            _json_response(self, {'error': audio_err}, 400)
            return
        if ref_audio_tuple is None:
            _json_response(self, {'error': 'No reference audio provided'}, 400)
            return

        ref_text = (data.get('ref_text') or '').strip() or None
        x_vector_only = data.get('x_vector_only', False)
        language = data.get('language', 'Auto')

        with request_count_lock:
            request_count += 1

        t0 = time.time()
        try:
            with generation_lock:
                wavs, sr = model.generate_voice_clone(
                    text=text,
                    language=language,
                    ref_audio=ref_audio_tuple,
                    ref_text=ref_text,
                    x_vector_only_mode=x_vector_only,
                    max_new_tokens=MAX_NEW_TOKENS,
                )
            elapsed = time.time() - t0
            logger.info(f"VoiceClone generated in {elapsed:.2f}s")
            _audio_response(self, wavs[0], sr)
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
