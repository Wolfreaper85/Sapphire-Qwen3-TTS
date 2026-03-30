"""Qwen3-TTS provider — local AI text-to-speech with voice cloning and design.

Routes generation requests to the Qwen3-TTS subprocess server based on
which saved voice profile the persona is using.

Auto-launches the server subprocess when the provider is created (same
lifecycle pattern as Kokoro, but self-contained in the plugin — no core
file changes required).

Voice ID format:
    qwen3:preset:{speaker}    — Built-in preset speaker (CustomVoice model)
    qwen3:{profile_id}        — Saved voice profile (design/clone/custom)
"""
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

import requests

from core.tts.providers.base import BaseTTSProvider
from core.process_manager import ProcessManager, kill_process_on_port

logger = logging.getLogger(__name__)

DEFAULT_PORT = 5013
DEFAULT_SPEAKER = 'ryan'

# Module-level server manager — persists across provider re-creation
_server_manager: Optional[ProcessManager] = None


def _get_settings():
    """Load plugin settings."""
    try:
        from core.plugin_loader import plugin_loader
        return plugin_loader.get_plugin_settings('qwen3-tts') or {}
    except Exception:
        return {}


def _get_port():
    """Get configured server port."""
    settings = _get_settings()
    try:
        return int(settings.get('server_port', DEFAULT_PORT))
    except (ValueError, TypeError):
        return DEFAULT_PORT


def _server_url():
    """Get the Qwen3-TTS server URL."""
    return f"http://localhost:{_get_port()}"


def _server_is_healthy():
    """Quick health check — is the server already responding?"""
    try:
        r = requests.get(f"{_server_url()}/health", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


def _start_server():
    """Start the Qwen3-TTS subprocess server if not already running."""
    global _server_manager

    # Already running?
    if _server_manager and _server_manager.is_running():
        return
    if _server_is_healthy():
        logger.info("[Qwen3-TTS] Server already running (external)")
        return

    plugin_dir = Path(__file__).parent
    server_script = plugin_dir / "server.py"
    if not server_script.exists():
        logger.error(f"[Qwen3-TTS] Server script not found: {server_script}")
        return

    base_dir = plugin_dir.parent.parent  # sapphire-dev root

    # Clean up orphaned process on our port
    port = _get_port()
    if kill_process_on_port(port):
        logger.info(f"[Qwen3-TTS] Cleaned up orphaned process on port {port}")

    # Build env vars for the server subprocess
    settings = _get_settings()
    env = os.environ.copy()
    env['QWEN3_TTS_PORT'] = str(port)
    env['QWEN3_TTS_DEVICE'] = settings.get('device', 'cuda:0')
    env['QWEN3_TTS_MODEL_SIZE'] = settings.get('model_size', '1.7B')

    # Ensure HF_HOME is set (Sapphire's Start Sapphire.bat sets this)
    if not env.get('HF_HOME'):
        portable_cache = base_dir.parent / '.hf_cache'
        if portable_cache.is_dir():
            env['HF_HOME'] = str(portable_cache)

    logger.info(f"[Qwen3-TTS] Starting server subprocess on port {port}...")
    _server_manager = ProcessManager(
        script_path=server_script,
        log_name="qwen3-tts",
        base_dir=base_dir,
    )
    # Inject env vars into the subprocess command
    _server_manager._env = env

    # Override start() to pass env — ProcessManager doesn't natively support env
    _start_with_env(_server_manager, env)
    _server_manager.monitor_and_restart(check_interval=15)

    # Don't block — the server loads models in the background.
    # The provider's generate() retries handle connection errors gracefully.
    time.sleep(1)
    logger.info("[Qwen3-TTS] Server subprocess launched (models loading in background)")


def _start_with_env(pm: ProcessManager, env: dict):
    """Start a ProcessManager subprocess with custom environment variables."""
    import subprocess as _subprocess

    if pm.script_path.suffix == '.py':
        pm.command = [sys.executable, str(pm.script_path)]

    logger.info(f"[Qwen3-TTS] Starting: {' '.join(pm.command)}")
    pm.log_file.parent.mkdir(parents=True, exist_ok=True)

    IS_WINDOWS = sys.platform == 'win32'
    with open(pm.log_file, "a") as log:
        if IS_WINDOWS:
            pm.process = _subprocess.Popen(
                pm.command, stdout=log, stderr=log, env=env
            )
        else:
            from core.process_manager import _make_child_die_with_parent
            pm.process = _subprocess.Popen(
                pm.command, stdout=log, stderr=log, env=env,
                preexec_fn=_make_child_die_with_parent
            )
    logger.info(f"[Qwen3-TTS] Server PID: {pm.process.pid}")


def _stop_server():
    """Stop the Qwen3-TTS subprocess server."""
    global _server_manager
    if _server_manager:
        _server_manager.stop()
        _server_manager = None
        logger.info("[Qwen3-TTS] Server stopped")


class Qwen3TTSProvider(BaseTTSProvider):
    """Generates audio via the local Qwen3-TTS subprocess server.

    Auto-launches the server when the provider is created.
    Auto-stops when the provider is garbage collected (provider switch).
    """

    audio_content_type = 'audio/ogg'
    SPEED_MIN = 0.5
    SPEED_MAX = 2.0

    def __init__(self):
        self._last_error = None
        logger.info("[Qwen3-TTS] Provider initialized — launching server")
        _start_server()

    def __del__(self):
        """Stop server when provider is replaced (hot-swap to another provider)."""
        try:
            _stop_server()
        except Exception:
            pass

    def generate(self, text: str, voice: str, speed: float, **kwargs) -> Optional[bytes]:
        """Generate audio. Dispatches to the right model based on voice ID format."""
        clamped_speed = max(self.SPEED_MIN, min(self.SPEED_MAX, speed))
        if clamped_speed != speed:
            logger.warning(f"Qwen3-TTS: clamped speed {speed} -> {clamped_speed}")

        server = _server_url()

        # Parse voice ID to determine generation mode
        if voice and voice.startswith('qwen3:preset:'):
            speaker = voice.split(':', 2)[2]
            return self._generate_custom(server, text, speaker, kwargs.get('instruct'), clamped_speed)

        elif voice and voice.startswith('qwen3:'):
            profile_id = voice.split(':', 1)[1]
            return self._generate_from_profile(server, text, profile_id, clamped_speed)

        else:
            speaker = voice if voice else DEFAULT_SPEAKER
            return self._generate_custom(server, text, speaker, kwargs.get('instruct'), clamped_speed)

    def _generate_custom(self, server: str, text: str, speaker: str,
                         instruct: Optional[str], speed: float) -> Optional[bytes]:
        """Generate using CustomVoice model (preset speaker + instruction)."""
        payload = {
            'text': text,
            'speaker': speaker,
            'language': 'Auto',
        }
        if instruct:
            payload['instruct'] = instruct
        return self._post(server, '/generate/custom', payload)

    def _generate_from_profile(self, server: str, text: str,
                               profile_id: str, speed: float) -> Optional[bytes]:
        """Load a saved voice profile and generate accordingly."""
        try:
            from voice_manager import voice_manager
        except ImportError:
            import os as _os
            plugin_dir = _os.path.dirname(_os.path.abspath(__file__))
            if plugin_dir not in sys.path:
                sys.path.insert(0, plugin_dir)
            from voice_manager import voice_manager

        profile = voice_manager.get_voice(profile_id)
        if not profile:
            logger.warning(f"Qwen3-TTS: voice profile '{profile_id}' not found, using default")
            return self._generate_custom(server, text, DEFAULT_SPEAKER, None, speed)

        if profile.type == 'custom_voice':
            return self._post(server, '/generate/custom', {
                'text': text,
                'speaker': profile.speaker,
                'instruct': profile.instruct or None,
                'language': profile.language,
            })
        elif profile.type == 'voice_design':
            return self._post(server, '/generate/design', {
                'text': text,
                'instruct': profile.instruct,
                'language': profile.language,
            })
        elif profile.type == 'voice_clone':
            return self._post(server, '/generate/clone', {
                'text': text,
                'ref_audio': profile.ref_audio,
                'ref_text': profile.ref_text or None,
                'x_vector_only': profile.x_vector_only,
                'language': profile.language,
            })
        else:
            logger.warning(f"Qwen3-TTS: unknown profile type '{profile.type}'")
            return self._generate_custom(server, text, DEFAULT_SPEAKER, None, speed)

    def _post(self, server: str, endpoint: str, payload: dict) -> Optional[bytes]:
        """POST to the Qwen3-TTS server with retry."""
        delays = [0.5, 1.0, 2.0]
        last_error = None

        for attempt in range(1 + len(delays)):
            try:
                response = requests.post(f"{server}{endpoint}", json=payload, timeout=120)
                if response.status_code == 200:
                    return response.content
                logger.error(f"Qwen3-TTS server error: {response.status_code} on {endpoint}")
                last_error = f"HTTP {response.status_code}"
                try:
                    err = response.json().get('error', '')
                    if err:
                        last_error = err
                except Exception:
                    pass
                if 400 <= response.status_code < 500:
                    break
            except Exception as e:
                last_error = str(e)

            if attempt < len(delays):
                logger.warning(f"Qwen3-TTS attempt {attempt + 1} failed, retrying in {delays[attempt]}s...")
                time.sleep(delays[attempt])

        logger.error(f"Qwen3-TTS generate failed after retries: {last_error}")
        self._last_error = last_error
        return None

    def is_available(self) -> bool:
        """Check if Qwen3-TTS server is reachable."""
        return _server_is_healthy()

    def list_voices(self) -> list:
        """Return all available voices (saved profiles + presets)."""
        try:
            from voice_manager import voice_manager
        except ImportError:
            try:
                plugin_dir = os.path.dirname(os.path.abspath(__file__))
                if plugin_dir not in sys.path:
                    sys.path.insert(0, plugin_dir)
                from voice_manager import voice_manager
            except ImportError:
                return []
        return voice_manager.get_all_for_provider()
