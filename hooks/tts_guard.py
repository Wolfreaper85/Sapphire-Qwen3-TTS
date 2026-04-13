# hooks/tts_guard.py
# Pre-TTS hook — universal voice/provider sync for persona switches.
#
# Cross-checks what the TTS client is about to use vs what the active persona
# is configured with. Handles BOTH directions:
#   - Persona has qwen3 voice but TTS client has kokoro → switch to qwen3-tts
#   - Persona has kokoro voice but TTS client has qwen3 → switch to kokoro
#
# The active persona's saved settings are the source of truth — not chat
# defaults, not whatever the TTS client initialized with.
#
# MUST be a sync function (not async). The hook_runner.fire() method calls
# handlers synchronously — async handlers are silently discarded.

import logging
import config

logger = logging.getLogger(__name__)

_last_error_count = 0  # Prevent error log spam


def pre_tts(event):
    """Cross-check TTS client voice/provider against the active persona."""
    global _last_error_count

    try:
        logger.info("[qwen3-tts] Guard: FIRED — pre_tts hook executing")

        from core.api_fastapi import get_system
        system = get_system()
        if not system or not hasattr(system, 'llm_chat'):
            logger.warning("[qwen3-tts] Guard: no system or no llm_chat — bailing")
            return

        # ── Get the persona's voice (source of truth) ────────────────────
        from core.personas.persona_manager import persona_manager
        chat_settings = system.llm_chat.session_manager.get_chat_settings()
        active_persona = chat_settings.get("persona", "")

        if not active_persona:
            logger.warning("[qwen3-tts] Guard: no active persona in chat settings — bailing")
            return

        pdata = persona_manager.get(active_persona)
        if not pdata or not isinstance(pdata, dict):
            logger.warning(f"[qwen3-tts] Guard: persona '{active_persona}' not found or invalid — bailing")
            return

        persona_settings = pdata.get("settings", {})
        persona_voice = persona_settings.get("voice", "")

        logger.info(f"[qwen3-tts] Guard: persona='{active_persona}', persona_voice='{persona_voice}', "
                     f"settings_keys={list(persona_settings.keys())}")

        if not persona_voice:
            logger.warning(f"[qwen3-tts] Guard: persona '{active_persona}' has no voice configured — bailing")
            return  # No voice configured on persona

        # ── Determine correct provider from voice ID ─────────────────────
        current_voice = getattr(system.tts, 'voice_name', None) or ''
        current_provider = getattr(config, 'TTS_PROVIDER', 'none')
        needs_fix = False

        if persona_voice.startswith("qwen3:"):
            # Persona wants qwen3-tts
            target_provider = 'qwen3-tts'
        else:
            # Persona wants a non-qwen3 voice (kokoro, etc.)
            target_provider = 'kokoro'

        # ── Provider mismatch — switch ───────────────────────────────────
        # IMPORTANT: switch_tts_provider() creates a NEW TTSClient, but speak()
        # is executing on the OLD one. We must update BOTH system.tts (for future
        # calls) AND the current tts client (the 'self' that called speak()).
        # We grab a ref to the caller BEFORE any switch so we can patch it too.
        caller_tts = system.tts  # The TTSClient currently executing speak()

        if current_provider != target_provider:
            from core.tts.providers import tts_registry
            if not tts_registry.get_entry(target_provider):
                logger.warning(f"[qwen3-tts] Guard: target provider '{target_provider}' not registered — bailing")
                return

            logger.info(f"[qwen3-tts] Guard: provider '{current_provider}' -> '{target_provider}' "
                        f"(persona '{active_persona}' voice='{persona_voice}')")

            from core.settings_manager import settings as _settings
            system.switch_tts_provider(target_provider)
            _settings.set('TTS_PROVIDER', target_provider, persist=True)
            needs_fix = True

        # ── Voice mismatch — fix it ──────────────────────────────────────
        # Update BOTH system.tts (new client if switched) AND caller_tts (old
        # client that is mid-speak). This ensures the daemon thread spawned by
        # speak() reads the correct voice_name from self.
        if current_voice != persona_voice:
            logger.info(f"[qwen3-tts] Guard: voice '{current_voice}' -> '{persona_voice}' "
                        f"(persona '{active_persona}')")
            system.tts.set_voice(persona_voice)
            if caller_tts is not system.tts:
                caller_tts.voice_name = persona_voice  # Patch the in-flight caller too
            needs_fix = True

        # ── Pitch/speed mismatch — sync from persona ─────────────────────
        persona_pitch = persona_settings.get("pitch")
        if persona_pitch is not None:
            current_pitch = getattr(caller_tts, 'pitch_shift', None)
            if current_pitch != persona_pitch:
                system.tts.set_pitch(persona_pitch)
                if caller_tts is not system.tts:
                    caller_tts.pitch_shift = float(persona_pitch)
                needs_fix = True

        persona_speed = persona_settings.get("speed")
        if persona_speed is not None:
            current_speed = getattr(caller_tts, 'speed', None)
            if current_speed != persona_speed:
                system.tts.set_speed(persona_speed)
                if caller_tts is not system.tts:
                    caller_tts.speed = float(persona_speed)
                needs_fix = True

        if needs_fix:
            logger.info(f"[qwen3-tts] Guard: synced persona '{active_persona}' -> "
                        f"provider={target_provider}, voice={persona_voice}, "
                        f"pitch={persona_pitch}, speed={persona_speed}")

        _last_error_count = 0

    except Exception as e:
        _last_error_count += 1
        if _last_error_count <= 3:
            logger.warning(f"[qwen3-tts] TTS guard error: {e}")
        elif _last_error_count == 4:
            logger.warning(f"[qwen3-tts] TTS guard errors suppressed (repeated failures)")
