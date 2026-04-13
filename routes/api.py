"""Qwen3-TTS plugin API routes.

All routes are mounted at /api/plugin/qwen3-tts/{path}.
Route handlers receive **kwargs with:
    body: dict    — parsed JSON body (POST)
    {param}: str  — path parameters
"""
import base64
import json
import logging
import os
import subprocess
import sys

import requests

logger = logging.getLogger(__name__)

# Ensure plugin dir is importable
_plugin_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _plugin_dir not in sys.path:
    sys.path.insert(0, _plugin_dir)

from voice_manager import voice_manager, PRESET_SPEAKERS, SUPPORTED_LANGUAGES


def _server_url():
    """Get the Qwen3-TTS server URL from plugin settings."""
    try:
        from core.plugin_loader import plugin_loader
        settings = plugin_loader.get_plugin_settings('qwen3-tts') or {}
        port = int(settings.get('server_port', 5013))
    except Exception:
        port = 5013
    return f"http://localhost:{port}"


# =============================================================================
# Voice Library CRUD
# =============================================================================

async def list_voices(**kwargs):
    """GET /api/plugin/qwen3-tts/voices — list all saved voices + presets."""
    saved = voice_manager.list_voices()
    return {
        "voices": saved,
        "presets": PRESET_SPEAKERS,
        "languages": SUPPORTED_LANGUAGES,
    }


async def get_voice(**kwargs):
    """GET /api/plugin/qwen3-tts/voices/{voice_id} — get a single voice profile."""
    voice_id = kwargs.get("voice_id", "")
    profile = voice_manager.get_voice(voice_id)
    if not profile:
        return {"error": "Voice not found"}
    return {"voice": profile.to_dict()}


async def save_voice(**kwargs):
    """POST /api/plugin/qwen3-tts/voices — save a voice profile.

    For clone voices, also pre-computes the voice_clone_prompt (.pt file)
    so persona TTS uses a cached embedding instead of re-encoding audio every time.
    """
    body = kwargs.get("body", {})
    if not body.get("name"):
        return {"error": "Voice name is required"}

    profile = voice_manager.save_voice(body)

    # Auto-create cached voice prompt for clone voices
    if profile.type == 'voice_clone' and profile.ref_audio:
        try:
            voice_dir = voice_manager.get_voice_dir(profile.type, profile.model_size)
            prompt_path = os.path.join(str(voice_dir), f"{profile.id}.pt")
            server = _server_url()
            r = requests.post(f"{server}/create-prompt", json={
                "ref_audio": profile.ref_audio,
                "ref_text": profile.ref_text or None,
                "x_vector_only": profile.x_vector_only,
                "save_path": prompt_path,
            }, timeout=60)
            if r.status_code == 200:
                # Update profile with prompt path
                profile.prompt_path = os.path.basename(prompt_path)
                voice_manager.save_voice(profile.to_dict())
                logger.info(f"Voice clone prompt cached for {profile.id}")
            else:
                logger.warning(f"Failed to cache voice prompt: {r.status_code}")
        except Exception as e:
            logger.warning(f"Failed to cache voice prompt: {e}")
            # Non-fatal — voice still works, just slower without cache

    return {"status": "saved", "voice": profile.to_dict()}


async def delete_voice(**kwargs):
    """DELETE /api/plugin/qwen3-tts/voices/{voice_id} — delete a voice profile."""
    voice_id = kwargs.get("voice_id", "")
    if voice_manager.delete_voice(voice_id):
        return {"status": "deleted"}
    return {"error": "Voice not found"}


# =============================================================================
# Audio Generation (Voice Lab)
# =============================================================================

async def generate_voice_design(**kwargs):
    """POST /api/plugin/qwen3-tts/generate/design — generate with voice description."""
    body = kwargs.get("body", {})
    text = (body.get("text") or "").strip()
    instruct = (body.get("instruct") or "").strip()
    language = body.get("language", "Auto")

    if not text:
        return {"error": "Text is required"}
    if not instruct:
        return {"error": "Voice description is required"}

    server = _server_url()
    try:
        r = requests.post(f"{server}/generate/design", json={
            "text": text,
            "instruct": instruct,
            "language": language,
            "seed": body.get("seed", -1),
            "temperature": body.get("temperature", 0.7),
        }, timeout=120)

        if r.status_code == 200:
            audio_b64 = base64.b64encode(r.content).decode('ascii')
            return {"status": "ok", "audio": audio_b64, "content_type": "audio/ogg"}
        else:
            err = "Generation failed"
            try:
                err = r.json().get("error", err)
            except Exception:
                pass
            return {"error": err}
    except requests.ConnectionError:
        return {"error": "Qwen3-TTS server not running. Start it from Settings."}
    except Exception as e:
        return {"error": str(e)}


async def generate_voice_clone(**kwargs):
    """POST /api/plugin/qwen3-tts/generate/clone — generate by cloning reference audio."""
    body = kwargs.get("body", {})
    text = (body.get("text") or "").strip()
    ref_audio = body.get("ref_audio", "")  # base64 or filename
    ref_text = (body.get("ref_text") or "").strip()
    x_vector_only = body.get("x_vector_only", False)
    language = body.get("language", "Auto")

    if not text:
        return {"error": "Target text is required"}
    if not ref_audio:
        return {"error": "Reference audio is required"}

    server = _server_url()
    try:
        r = requests.post(f"{server}/generate/clone", json={
            "text": text,
            "ref_audio": ref_audio,
            "ref_text": ref_text or None,
            "x_vector_only": x_vector_only,
            "language": language,
            "seed": body.get("seed", -1),
            "temperature": body.get("temperature", 0.7),
        }, timeout=120)

        if r.status_code == 200:
            audio_b64 = base64.b64encode(r.content).decode('ascii')
            return {"status": "ok", "audio": audio_b64, "content_type": "audio/ogg"}
        else:
            err = "Clone failed"
            try:
                err = r.json().get("error", err)
            except Exception:
                pass
            return {"error": err}
    except requests.ConnectionError:
        return {"error": "Qwen3-TTS server not running. Start it from Settings."}
    except Exception as e:
        return {"error": str(e)}


async def generate_custom_voice(**kwargs):
    """POST /api/plugin/qwen3-tts/generate/custom — generate with preset speaker."""
    body = kwargs.get("body", {})
    text = (body.get("text") or "").strip()
    speaker = body.get("speaker", "ryan")
    instruct = (body.get("instruct") or "").strip()
    language = body.get("language", "Auto")

    if not text:
        return {"error": "Text is required"}

    server = _server_url()
    try:
        r = requests.post(f"{server}/generate/custom", json={
            "text": text,
            "speaker": speaker.lower().replace(' ', '_'),
            "instruct": instruct or None,
            "language": language,
            "seed": body.get("seed", -1),
            "temperature": body.get("temperature", 0.7),
        }, timeout=120)

        if r.status_code == 200:
            audio_b64 = base64.b64encode(r.content).decode('ascii')
            return {"status": "ok", "audio": audio_b64, "content_type": "audio/ogg"}
        else:
            err = "Generation failed"
            try:
                err = r.json().get("error", err)
            except Exception:
                pass
            return {"error": err}
    except requests.ConnectionError:
        return {"error": "Qwen3-TTS server not running. Start it from Settings."}
    except Exception as e:
        return {"error": str(e)}


async def generate_preview(**kwargs):
    """POST /api/plugin/qwen3-tts/generate/preview — preview any voice configuration."""
    body = kwargs.get("body", {})
    voice_type = body.get("type", "custom_voice")

    # Dispatch to the right generator
    if voice_type == "voice_design":
        return await generate_voice_design(**kwargs)
    elif voice_type == "voice_clone":
        return await generate_voice_clone(**kwargs)
    else:
        return await generate_custom_voice(**kwargs)


# =============================================================================
# Voice Prompt Caching
# =============================================================================

async def create_prompt(**kwargs):
    """POST /api/plugin/qwen3-tts/create-prompt — pre-compute voice clone prompt.

    Creates a .pt file with cached speaker embeddings so persona TTS
    doesn't re-encode reference audio on every request.
    """
    body = kwargs.get("body", {})
    ref_audio = body.get("ref_audio", "")
    ref_text = body.get("ref_text")
    x_vector_only = body.get("x_vector_only", False)
    save_path = body.get("save_path", "")

    if not ref_audio:
        return {"error": "ref_audio is required"}
    if not save_path:
        return {"error": "save_path is required"}

    server = _server_url()
    try:
        r = requests.post(f"{server}/create-prompt", json={
            "ref_audio": ref_audio,
            "ref_text": ref_text,
            "x_vector_only": x_vector_only,
            "save_path": save_path,
        }, timeout=60)
        if r.status_code == 200:
            return r.json()
        err = "Failed to create voice prompt"
        try:
            err = r.json().get("error", err)
        except Exception:
            pass
        return {"error": err}
    except requests.ConnectionError:
        return {"error": "Qwen3-TTS server not running."}
    except Exception as e:
        return {"error": str(e)}


# =============================================================================
# Server Status & Upload
# =============================================================================

async def get_status(**kwargs):
    """GET /api/plugin/qwen3-tts/status — check server health."""
    server = _server_url()
    try:
        r = requests.get(f"{server}/health", timeout=3)
        if r.status_code == 200:
            data = r.json()
            return {"running": True, **data}
        return {"running": False, "error": f"HTTP {r.status_code}"}
    except requests.ConnectionError:
        return {"running": False, "error": "Server not running"}
    except Exception as e:
        return {"running": False, "error": str(e)}


async def change_model_size(**kwargs):
    """POST /api/plugin/qwen3-tts/change-model-size — switch model size and restart server.

    Body: { "model_size": "0.6B" | "1.7B" }
    Saves the setting and kills the current server so it relaunches with the new size.
    """
    body = kwargs.get("body", {})
    new_size = body.get("model_size", "").strip()
    if new_size not in ("0.6B", "1.7B"):
        return {"error": f"Invalid model size: {new_size}. Must be '0.6B' or '1.7B'"}

    try:
        from core.plugin_loader import plugin_loader, PROJECT_ROOT
        # Read current settings and update model_size
        current = plugin_loader.get_plugin_settings('qwen3-tts') or {}
        current['model_size'] = new_size

        # Save via the standard settings path
        settings_dir = PROJECT_ROOT / "user" / "webui" / "plugins"
        settings_dir.mkdir(parents=True, exist_ok=True)
        settings_file = settings_dir / 'qwen3-tts.json'

        with open(settings_file, 'w') as f:
            json.dump(current, f, indent=2)

        logger.info(f"[Qwen3-TTS] Model size changed to {new_size}")

        # Kill the current server and relaunch with new size
        try:
            from core.process_manager import kill_process_on_port
            port = int(current.get('server_port', 5013))
            if kill_process_on_port(port):
                logger.info(f"[Qwen3-TTS] Killed server on port {port} for model size switch")

            # Brief pause for port to free, then relaunch via provider module
            import time
            time.sleep(1)
            try:
                from provider import _start_server
                _start_server()
                logger.info(f"[Qwen3-TTS] Relaunched server with {new_size}")
            except Exception as e2:
                logger.warning(f"[Qwen3-TTS] Auto-relaunch failed (will start on next generate): {e2}")
        except Exception as e:
            logger.warning(f"[Qwen3-TTS] Could not kill server for restart: {e}")

        return {"status": "ok", "model_size": new_size, "message": f"Switched to {new_size}. Server restarting..."}
    except Exception as e:
        logger.error(f"[Qwen3-TTS] Failed to change model size: {e}")
        return {"error": str(e)}


async def open_folder(**kwargs):
    """POST /api/plugin/qwen3-tts/open-folder — open a plugin folder in file explorer.

    Body: { "target": "voices" | "plugin" }  (default: "voices")
    """
    body = kwargs.get("body", {})
    target = body.get("target", "voices")
    if target == "plugin":
        folder = _plugin_dir
    else:
        folder = os.path.join(_plugin_dir, "voices")
    os.makedirs(folder, exist_ok=True)
    try:
        if sys.platform == "win32":
            os.startfile(folder)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
        return {"status": "ok", "path": folder}
    except Exception as e:
        return {"error": str(e)}


async def upload_reference_audio(**kwargs):
    """POST /api/plugin/qwen3-tts/upload-ref — upload reference audio for cloning.

    Expects body.audio as base64-encoded audio data.
    Saves to voices/audio/ and returns the filename.
    """
    body = kwargs.get("body", {})
    audio_b64 = body.get("audio", "")
    if not audio_b64:
        return {"error": "No audio data provided"}

    try:
        audio_bytes = base64.b64decode(audio_b64)
    except Exception:
        return {"error": "Invalid base64 audio data"}

    # Detect extension from first bytes
    ext = ".wav"
    if audio_bytes[:4] == b'fLaC':
        ext = ".flac"
    elif audio_bytes[:3] == b'ID3' or audio_bytes[:2] == b'\xff\xfb':
        ext = ".mp3"
    elif audio_bytes[:4] == b'OggS':
        ext = ".ogg"

    # Save to the correct subdirectory based on voice type
    voice_type = body.get("voice_type", "voice_clone")  # uploads are typically for clones
    model_size = body.get("model_size", "0.6B")
    filename = voice_manager.save_audio_file(audio_bytes, voice_type=voice_type, model_size=model_size, prefix="ref", ext=ext)
    return {"status": "uploaded", "filename": filename}


# =============================================================================
# Silent Mode — full TTS unload to free VRAM
# =============================================================================

# Persist state to disk so restarts can restore properly
_SILENT_STATE_FILE = os.path.join(_plugin_dir, '.silent_mode_state.json')


def _load_silent_state():
    """Load silent mode state from disk. Returns dict with 'active' and 'previous_provider'."""
    try:
        if os.path.exists(_SILENT_STATE_FILE):
            with open(_SILENT_STATE_FILE, 'r') as f:
                data = json.load(f)
            return {
                'active': bool(data.get('active', False)),
                'previous_provider': data.get('previous_provider'),
            }
    except Exception as e:
        logger.warning(f"[Silent Mode] Failed to load state file: {e}")
    return {'active': False, 'previous_provider': None}


def _save_silent_state(active, previous_provider=None):
    """Persist silent mode state to disk."""
    try:
        with open(_SILENT_STATE_FILE, 'w') as f:
            json.dump({'active': active, 'previous_provider': previous_provider}, f)
    except Exception as e:
        logger.warning(f"[Silent Mode] Failed to save state file: {e}")


async def enable_silent_mode(**kwargs):
    """POST /api/plugin/qwen3-tts/silent-mode/on — kill all TTS servers and free VRAM.

    Switches TTS to 'none', kills Qwen3-TTS and F5-TTS subprocess servers,
    and frees all GPU memory used by voice models.
    """
    from core.process_manager import kill_process_on_port
    from core.settings_manager import settings as _settings
    import time as _time

    state = _load_silent_state()
    if state['active']:
        return {"status": "already_silent", "message": "Silent mode is already active"}

    # Remember current provider so we can restore it
    try:
        import config as _config
        current_provider = getattr(_config, 'TTS_PROVIDER', 'none')
    except Exception:
        current_provider = 'none'

    # Persist state to disk BEFORE switching — survives restarts
    _save_silent_state(active=True, previous_provider=current_provider)

    killed = []

    # 1. Switch TTS to none via the system object (monkey-patch safe)
    try:
        from core.api_fastapi import get_system
        system = get_system()
        system.switch_tts_provider('none')
        _settings.set('TTS_PROVIDER', 'none', persist=True)
        logger.info("[Silent Mode] TTS provider switched to 'none'")
    except Exception as e:
        logger.error(f"[Silent Mode] Failed to switch provider: {e}")

    # 2. Kill Qwen3-TTS server subprocess
    try:
        from provider import _stop_server as _stop_qwen3, _server_manager as _qwen3_mgr
        _stop_qwen3()
        logger.info("[Silent Mode] Qwen3-TTS server stopped")
        killed.append('qwen3-tts')
    except Exception:
        pass
    # Belt-and-suspenders: kill by port
    try:
        from core.plugin_loader import plugin_loader
        _psettings = plugin_loader.get_plugin_settings('qwen3-tts') or {}
        port = int(_psettings.get('server_port', 5013))
        if kill_process_on_port(port):
            logger.info(f"[Silent Mode] Killed process on port {port}")
            if 'qwen3-tts' not in killed:
                killed.append('qwen3-tts')
    except Exception:
        pass

    # 3. Kill F5-TTS server subprocess
    try:
        f5_port = 5014
        if kill_process_on_port(f5_port):
            logger.info(f"[Silent Mode] Killed F5-TTS on port {f5_port}")
            killed.append('f5-tts')
    except Exception:
        pass

    # 4. Kill Kokoro server
    try:
        kokoro_port = 5012
        if kill_process_on_port(kokoro_port):
            logger.info(f"[Silent Mode] Killed Kokoro on port {kokoro_port}")
            killed.append('kokoro')
    except Exception:
        pass

    logger.info(f"[Silent Mode] ACTIVE — killed: {killed}, previous provider: {current_provider}")
    return {
        "status": "silent",
        "killed": killed,
        "previous_provider": current_provider,
        "message": f"Silent mode active. Killed {', '.join(killed) or 'no servers'}. VRAM freed."
    }


async def disable_silent_mode(**kwargs):
    """POST /api/plugin/qwen3-tts/silent-mode/off — restore TTS and relaunch servers.

    Restores the previous TTS provider and relaunches the appropriate server.
    Also handles the 'zombie' case where Sapphire restarted during silent mode —
    TTS_PROVIDER is 'none' but in-memory state was lost. The disk state file
    preserves the previous provider across restarts.
    """
    from core.settings_manager import settings as _settings

    state = _load_silent_state()
    if not state['active']:
        # Check for zombie state: TTS_PROVIDER is 'none' but disk state says inactive
        # This happens if someone manually cleared the state or there's a mismatch
        try:
            import config as _config
            if getattr(_config, 'TTS_PROVIDER', 'none') == 'none':
                # Zombie detected — force restore to qwen3-tts
                logger.warning("[Silent Mode] Zombie state detected — TTS is 'none' but silent mode not active. Force-restoring.")
                previous = 'qwen3-tts'
                from core.api_fastapi import get_system
                system = get_system()
                success = system.switch_tts_provider(previous)
                if success:
                    _settings.set('TTS_PROVIDER', previous, persist=True)
                    _save_silent_state(active=False, previous_provider=None)
                    logger.info(f"[Silent Mode] Zombie fixed — restored provider: {previous}")
                    return {
                        "status": "voice_restored",
                        "provider": previous,
                        "message": f"Voice restored to {previous}. Server launching..."
                    }
        except Exception:
            pass
        return {"status": "not_silent", "message": "Silent mode is not active"}

    previous = state.get('previous_provider') or 'qwen3-tts'

    # Clear state file BEFORE restoring — even if restore fails, we don't stay stuck
    _save_silent_state(active=False, previous_provider=None)

    # Restore the TTS provider — this will auto-launch the server
    try:
        from core.api_fastapi import get_system
        system = get_system()
        success = system.switch_tts_provider(previous)
        if success:
            _settings.set('TTS_PROVIDER', previous, persist=True)
            logger.info(f"[Silent Mode] OFF — restored provider: {previous}")
            return {
                "status": "voice_restored",
                "provider": previous,
                "message": f"Voice restored to {previous}. Server launching..."
            }
        else:
            logger.error(f"[Silent Mode] Failed to restore provider: {previous}")
            return {"status": "error", "message": f"Failed to restore {previous}"}
    except Exception as e:
        logger.error(f"[Silent Mode] Restore error: {e}")
        return {"status": "error", "message": str(e)}


async def get_silent_mode_status(**kwargs):
    """GET /api/plugin/qwen3-tts/silent-mode — check if silent mode is active."""
    state = _load_silent_state()

    # Also detect zombie state for the UI
    is_zombie = False
    if not state['active']:
        try:
            import config as _config
            if getattr(_config, 'TTS_PROVIDER', 'none') == 'none':
                is_zombie = True
        except Exception:
            pass

    return {
        "active": state['active'] or is_zombie,
        "previous_provider": state.get('previous_provider') or ('qwen3-tts' if is_zombie else None),
        "zombie": is_zombie,
    }
