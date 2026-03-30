"""Qwen3-TTS plugin API routes.

All routes are mounted at /api/plugin/qwen3-tts/{path}.
Route handlers receive **kwargs with:
    body: dict    — parsed JSON body (POST)
    {param}: str  — path parameters
"""
import base64
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
    """POST /api/plugin/qwen3-tts/voices — save a voice profile."""
    body = kwargs.get("body", {})
    if not body.get("name"):
        return {"error": "Voice name is required"}

    profile = voice_manager.save_voice(body)
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


async def open_folder(**kwargs):
    """POST /api/plugin/qwen3-tts/open-folder — open voices/audio folder in file explorer."""
    audio_dir = os.path.join(_plugin_dir, "voices", "audio")
    os.makedirs(audio_dir, exist_ok=True)
    try:
        if sys.platform == "win32":
            os.startfile(audio_dir)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", audio_dir])
        else:
            subprocess.Popen(["xdg-open", audio_dir])
        return {"status": "ok", "path": audio_dir}
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

    filename = voice_manager.save_audio_file(audio_bytes, prefix="ref", ext=ext)
    return {"status": "uploaded", "filename": filename}
