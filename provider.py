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
import threading
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
_last_relaunch_attempt: float = 0.0  # Cooldown to prevent restart loops


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


def _server_matches_settings():
    """Check if the running server's config matches current plugin settings.

    Returns True if the server is running with the expected model_size.
    If not, returns False so the caller can kill and relaunch.
    """
    try:
        r = requests.get(f"{_server_url()}/health", timeout=2.0)
        if r.status_code != 200:
            return False
        data = r.json()
        settings = _get_settings()
        expected_size = settings.get('model_size', '0.6B')
        running_size = data.get('model_size', '')
        if running_size != expected_size:
            logger.warning(
                f"[Qwen3-TTS] Server mismatch: running {running_size}, settings want {expected_size}"
            )
            return False
        return True
    except Exception:
        return False


def _start_server():
    """Start the Qwen3-TTS subprocess server if not already running."""
    global _server_manager

    # Already running and managed by us?
    if _server_manager and _server_manager.is_running():
        return

    # External server already on the port? Check if it matches our settings.
    if _server_is_healthy():
        if _server_matches_settings():
            logger.info("[Qwen3-TTS] Server already running (external, settings match)")
            return
        else:
            # Settings changed (e.g. model_size switched) — kill stale server
            logger.warning("[Qwen3-TTS] Killing stale server (settings mismatch)...")
            port = _get_port()
            if kill_process_on_port(port):
                logger.info(f"[Qwen3-TTS] Killed stale server on port {port}")
            time.sleep(1)  # Brief pause for port to free up

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
    env['QWEN3_TTS_MODEL_SIZE'] = settings.get('model_size', '0.6B')
    env['QWEN3_TTS_LOAD_MODELS'] = settings.get('load_models', 'all')
    env['QWEN3_TTS_OFFLOAD_TIMEOUT'] = str(settings.get('offload_timeout', '60'))

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
    _server_manager._env = env

    # Monkey-patch start() so both initial launch AND monitor_and_restart()
    # use our custom env vars.  Without this, the monitor's self.start()
    # launches without env vars and the server falls back to defaults.
    def _patched_start():
        _start_with_env(_server_manager, env)
    _server_manager.start = _patched_start

    _server_manager.start()
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
        logger.info(f"[Qwen3-TTS] generate() called with voice='{voice}', speed={speed}")
        clamped_speed = max(self.SPEED_MIN, min(self.SPEED_MAX, speed))
        if clamped_speed != speed:
            logger.warning(f"Qwen3-TTS: clamped speed {speed} -> {clamped_speed}")

        # Auto-relaunch server if it crashed (max once per 120s to avoid loops)
        global _last_relaunch_attempt
        if not _server_is_healthy():
            now = time.time()
            if now - _last_relaunch_attempt > 120:
                _last_relaunch_attempt = now
                logger.warning("[Qwen3-TTS] Server not healthy, attempting relaunch...")
                _start_server()
            else:
                logger.warning("[Qwen3-TTS] Server not healthy, skipping relaunch (cooldown)")
                return None

        server = _server_url()

        # Parse voice ID to determine generation mode
        if voice and voice.startswith('qwen3:preset:'):
            speaker = voice.split(':', 2)[2]
            logger.info(f"[Qwen3-TTS] -> preset speaker: {speaker}")
            return self._generate_custom(server, text, speaker, kwargs.get('instruct'), clamped_speed)

        elif voice and voice.startswith('qwen3:'):
            profile_id = voice.split(':', 1)[1]
            logger.info(f"[Qwen3-TTS] -> profile: {profile_id}")
            return self._generate_from_profile(server, text, profile_id, clamped_speed)

        else:
            # Non-qwen3 voice ID — always fall back to DEFAULT_SPEAKER.
            # Unknown voices (af_heart, f5:xxx, empty string, etc.) should
            # never be sent as a CustomVoice speaker name.
            logger.warning(f"[Qwen3-TTS] -> non-qwen3 voice '{voice}', falling back to default speaker: {DEFAULT_SPEAKER}")
            return self._generate_custom(server, text, DEFAULT_SPEAKER, kwargs.get('instruct'), clamped_speed)

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
            payload = {
                'text': text,
                'language': profile.language,
            }
            # Use cached voice prompt if available (faster + more consistent)
            if profile.prompt_path:
                plugin_dir = Path(__file__).parent
                prompt_full_path = plugin_dir / "voices" / profile.prompt_path
                if prompt_full_path.exists():
                    payload['prompt_path'] = str(prompt_full_path)
                    return self._post(server, '/generate/clone', payload)

            # Fallback to raw ref audio
            payload['ref_audio'] = profile.ref_audio
            payload['ref_text'] = profile.ref_text or None
            payload['x_vector_only'] = profile.x_vector_only
            audio = self._post(server, '/generate/clone', payload)

            # Auto-cache: create .pt prompt in background on first successful use
            if audio and profile.ref_audio:
                self._auto_cache_prompt(server, profile, voice_manager)

            return audio
        else:
            logger.warning(f"Qwen3-TTS: unknown profile type '{profile.type}'")
            return self._generate_custom(server, text, DEFAULT_SPEAKER, None, speed)

    def _auto_cache_prompt(self, server: str, profile, voice_manager):
        """Create a .pt voice clone prompt cache in the background.

        Called automatically on first successful generation for a clone voice
        that has no cached prompt. Updates the voice profile with the new
        prompt_path so subsequent calls skip ref-audio re-encoding.
        """
        def _do_cache():
            try:
                plugin_dir = Path(__file__).parent
                pt_filename = f"{profile.id}.pt"
                save_path = plugin_dir / "voices" / pt_filename
                audio_path = plugin_dir / "voices" / "audio" / profile.ref_audio

                if not audio_path.exists():
                    logger.warning(f"[Qwen3-TTS] Auto-cache skipped: ref audio not found: {audio_path}")
                    return

                r = requests.post(f"{server}/create-prompt", json={
                    "ref_audio": profile.ref_audio,
                    "ref_text": profile.ref_text or None,
                    "x_vector_only": profile.x_vector_only,
                    "save_path": str(save_path),
                }, timeout=60)

                if r.status_code == 200:
                    # Update profile with the cached prompt path
                    profile.prompt_path = pt_filename
                    voice_manager.save_voice(profile.to_dict())
                    logger.info(f"[Qwen3-TTS] Auto-cached voice prompt for '{profile.name}' -> {pt_filename}")
                else:
                    logger.warning(f"[Qwen3-TTS] Auto-cache failed: HTTP {r.status_code}")
            except Exception as e:
                logger.warning(f"[Qwen3-TTS] Auto-cache error: {e}")

        thread = threading.Thread(target=_do_cache, daemon=True, name=f"qwen3-cache-{profile.id}")
        thread.start()

    def _post(self, server: str, endpoint: str, payload: dict) -> Optional[bytes]:
        """POST to the Qwen3-TTS server with retry."""
        delays = [0.5, 1.0, 2.0]
        last_error = None

        for attempt in range(1 + len(delays)):
            try:
                response = requests.post(f"{server}{endpoint}", json=payload, timeout=300)
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
        return self._load_voices()

    @classmethod
    def list_voices_static(cls) -> list:
        """Return voices without needing a provider instance (no server spin-up)."""
        return cls._load_voices()

    @staticmethod
    def _load_voices() -> list:
        """Shared voice listing logic for instance and static methods."""
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
