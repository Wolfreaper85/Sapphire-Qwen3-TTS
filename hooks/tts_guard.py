# hooks/tts_guard.py
# Pre-TTS hook — auto-switches to qwen3-tts provider when the active voice
# requires it but the system is still on a different provider (e.g. kokoro),
# AND ensures the correct voice is set on the TTS client even if the provider
# was already switched but the voice wasn't applied.
#
# This fixes a startup race condition where _apply_initial_chat_settings runs
# before plugin providers are registered, causing the qwen3 voice to be
# silently replaced by the kokoro default.

import logging
import config

logger = logging.getLogger(__name__)

_fixed = False  # Only needs to fix once per session


async def pre_tts(event):
    """Pre-TTS hook: detect qwen3 voice on wrong provider or wrong voice and fix it."""
    global _fixed
    if _fixed:
        return

    try:
        # Check if the active chat's persona wants a qwen3 voice
        from core.api_fastapi import get_system
        system = get_system()
        if not system or not hasattr(system, 'llm_chat'):
            return

        settings = system.llm_chat.session_manager.get_chat_settings()
        voice = settings.get("voice", "")

        if not voice or not voice.startswith("qwen3:"):
            _fixed = True  # Not a qwen3 voice, no fix needed
            return

        current_provider = getattr(config, 'TTS_PROVIDER', 'none')

        # Check if provider needs switching
        if current_provider != 'qwen3-tts':
            from core.tts.providers import tts_registry
            if not tts_registry.get_entry('qwen3-tts'):
                return  # Provider not registered yet

            logger.info(f"[qwen3-tts] Auto-fixing provider: {current_provider} -> qwen3-tts (voice={voice})")

            from core.settings_manager import settings as _settings
            system.switch_tts_provider('qwen3-tts')
            _settings.set('TTS_PROVIDER', 'qwen3-tts', persist=True)

        # Always re-apply the correct voice from chat settings
        # (even if provider was already qwen3-tts, the voice may be wrong)
        current_voice = getattr(system.tts, 'voice_name', None) or ''
        if current_voice != voice:
            logger.info(f"[qwen3-tts] Fixing voice: '{current_voice}' -> '{voice}'")
            system.tts.set_voice(voice)

        if "pitch" in settings:
            system.tts.set_pitch(settings["pitch"])
        if "speed" in settings:
            system.tts.set_speed(settings["speed"])

        logger.info(f"[qwen3-tts] Provider and voice restored: {voice}")
        _fixed = True

    except Exception as e:
        logger.warning(f"[qwen3-tts] TTS guard hook error: {e}")
        _fixed = True  # Don't retry endlessly
