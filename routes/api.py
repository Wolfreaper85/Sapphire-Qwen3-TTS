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
