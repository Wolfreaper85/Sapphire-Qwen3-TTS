# hooks/tts_guard.py
# Pre-TTS hook — universal voice/provider sync for persona switches.
#
# Two layers of defense against the 2.4.9→2.5.7 auto-switch regression:
#
#   Layer A (PROACTIVE — added 2026-04-14): Module-level monkey-patch of
#   core.tts.utils.validate_voice (and its aliases in api_fastapi and routes/tts)
#   so that when a persona is activated, the TTS provider is switched to match
#   the voice prefix BEFORE _apply_chat_settings calls set_voice. This restores
#   the behavior that was in core/api_fastapi.py:_apply_chat_settings() in 2.4.9
#   and removed in 2.5.7 — but via runtime patching, not a core file edit.
#
#   Layer B (DEFENSIVE — pre_tts hook): Fires on every TTS generation. Reads
#   persona's voice from disk (source of truth) and re-syncs provider/voice/
#   pitch/speed if anything got out of alignment. Expanded 2026-04-14 to handle
#   f5 and elevenlabs prefixes in addition to qwen3 and kokoro.
#
# MUST be sync functions (not async). hook_runner.fire() calls handlers
# synchronously — async handlers are silently discarded.

import logging
import config

logger = logging.getLogger(__name__)

_last_error_count = 0  # Prevent error log spam


# ═══════════════════════════════════════════════════════════════════════════
# Shared prefix detection
# ═══════════════════════════════════════════════════════════════════════════

def _voice_provider_prefix(voice: str) -> str:
    """Extract provider prefix from a prefixed voice ID. Returns '' if no prefix."""
    if not voice or ':' not in voice:
        return ''
    prefix = voice.split(':', 1)[0]
    if prefix in ('qwen3', 'f5'):
        return prefix
    return ''


def _looks_like_elevenlabs(voice: str) -> bool:
    """ElevenLabs voice IDs are 20+ alphanumeric characters, no separator."""
    if not voice or ':' in voice or '_' in voice:
        return False
    return len(voice) >= 20 and voice.isalnum()


def _target_provider_for_voice(voice: str) -> str:
    """Determine which TTS provider should play a given voice ID."""
    if not voice:
        return ''
    prefix = _voice_provider_prefix(voice)
    if prefix == 'qwen3':
        return 'qwen3-tts'
    if prefix == 'f5':
        return 'f5-tts'
    if _looks_like_elevenlabs(voice):
        return 'elevenlabs'
    # Default: kokoro-style (af_*, am_*, bf_*, bm_*) or plain defaults
    return 'kokoro'


# ═══════════════════════════════════════════════════════════════════════════
# Layer A: Proactive provider auto-switch via validate_voice monkey-patch
# ═══════════════════════════════════════════════════════════════════════════

def _auto_switch_provider_for_voice(voice: str) -> None:
    """If voice belongs to a different provider than active, switch providers.

    Only switches when the target provider is actually registered (so e.g.
    f5-tts voices don't trigger a switch if f5-tts plugin isn't installed).
    Persists the new TTS_PROVIDER via settings manager.
    """
    if not voice:
        return
    try:
        target = _target_provider_for_voice(voice)
        if not target:
            return

        current = getattr(config, 'TTS_PROVIDER', 'none')
        if current == target:
            return

        # Only switch to providers that are actually registered
        from core.tts.providers import tts_registry
        if not tts_registry.get_entry(target):
            logger.debug(
                f"[qwen3-tts] auto-switch skipped: target '{target}' not registered "
                f"(voice='{voice}')"
            )
            return

        from core.api_fastapi import get_system
        system = get_system()
        if not system:
            return

        logger.info(
            f"[qwen3-tts] Auto-switching TTS provider: {current} -> {target} "
            f"(voice='{voice}')"
        )

        from core.settings_manager import settings as _settings
        system.switch_tts_provider(target)
        _settings.set('TTS_PROVIDER', target, persist=True)

    except Exception as e:
        logger.warning(f"[qwen3-tts] auto-switch error: {e}")


_patch_installed = False


def _install_validate_voice_patch() -> None:
    """Monkey-patch validate_voice to auto-switch provider before validation.

    Patches THREE references because Python imports are by-value:
      1. core.tts.utils.validate_voice — the source
      2. core.api_fastapi._validate_tts_voice — consumer's aliased import
      3. core.routes.tts._validate_tts_voice — another consumer's aliased import

    Without patching all three, consumers that already imported the original
    reference at their module load time would keep calling the old version.
    """
    global _patch_installed
    if _patch_installed:
        return

    try:
        from core.tts import utils as _tts_utils
    except ImportError:
        logger.warning("[qwen3-tts] Could not import core.tts.utils — auto-switch patch skipped")
        return

    original = _tts_utils.validate_voice

    def patched_validate_voice(voice, provider=None):
        # Auto-switch provider BEFORE validation, so validator sees correct state
        _auto_switch_provider_for_voice(voice)
        # Fall through to original validator (now running against switched provider)
        return original(voice, provider)

    # Patch the source
    _tts_utils.validate_voice = patched_validate_voice

    # Patch the consumer aliases. If modules aren't loaded yet, that's fine —
    # they'll import the patched version via _tts_utils.validate_voice.
    try:
        from core import api_fastapi as _api_fastapi
        if hasattr(_api_fastapi, '_validate_tts_voice'):
            _api_fastapi._validate_tts_voice = patched_validate_voice
    except ImportError:
        pass

    try:
        from core.routes import tts as _routes_tts
        if hasattr(_routes_tts, '_validate_tts_voice'):
            _routes_tts._validate_tts_voice = patched_validate_voice
    except ImportError:
        pass

    _patch_installed = True
    logger.info(
        "[qwen3-tts] validate_voice auto-switch patch installed "
        "(qwen3/f5/elevenlabs/kokoro prefix routing restored)"
    )


# Install the patch at module import time. Plugin loader imports this file
# during plugin initialization, which happens before persona activation.
_install_validate_voice_patch()


# ═══════════════════════════════════════════════════════════════════════════
# Layer C: Aggregate voices from ALL registered providers in /api/tts/voices
# ═══════════════════════════════════════════════════════════════════════════
# The core endpoint at core/routes/tts.py only returns voices from the ACTIVE
# provider, so the persona editor dropdown hides Kokoro voices when qwen3-tts
# is active (and vice versa). This makes it impossible to assign a persona
# a voice from another provider — even though auto-switch (Layer A) would
# then route correctly at runtime.
#
# Fix: walk app.routes, find the GET /api/tts/voices route, and replace its
# endpoint with one that aggregates voices across every registered provider.
# Each provider's list_voices_static() is preferred (no server spin-up); for
# providers without that, we fall back to the active provider's list_voices
# or a safe empty list.

_voices_patch_installed = False


def _aggregate_all_voices():
    """Collect voices from every registered TTS provider.

    Preference order per provider:
      1. If the provider is the ACTIVE one, use system.tts.provider.list_voices()
         (already-instantiated, returns current state).
      2. Else, call ProviderClass.list_voices_static() if available (no init).
      3. Else, skip (avoids triggering heavy provider init like ElevenLabs
         which needs an API key).
    """
    from core.tts.providers import tts_registry
    import config as _cfg

    active_key = getattr(_cfg, 'TTS_PROVIDER', 'none')
    active_provider_instance = None
    try:
        from core.api_fastapi import get_system
        _sys = get_system()
        if _sys and getattr(_sys, 'tts', None):
            active_provider_instance = getattr(_sys.tts, 'provider', None)
    except Exception:
        pass

    aggregated = []
    seen_ids = set()

    # _core and _plugins are the registry's internal dicts; combine them
    all_entries = {**getattr(tts_registry, '_core', {}),
                   **getattr(tts_registry, '_plugins', {})}

    for key, entry in all_entries.items():
        if key == 'none':
            continue
        provider_cls = entry.get('class')
        if not provider_cls:
            continue
        voices = []
        try:
            if key == active_key and active_provider_instance is not None:
                # Use the live instance for the currently-active provider
                voices = active_provider_instance.list_voices() or []
            elif hasattr(provider_cls, 'list_voices_static'):
                voices = provider_cls.list_voices_static() or []
            elif key == 'kokoro':
                # Kokoro's list_voices is a cheap instance method (just returns
                # a static list). Instantiating it doesn't spin up the server.
                try:
                    voices = provider_cls().list_voices() or []
                except Exception:
                    voices = []
            # else: skip providers that need instance init (e.g. ElevenLabs
            # requires api_key). Their voices will only appear when active.
        except Exception as e:
            logger.debug(f"[qwen3-tts] list_voices for '{key}' failed: {e}")
            continue

        # Tag each voice with provider key so the frontend can group/filter
        for v in voices:
            if not isinstance(v, dict):
                continue
            vid = v.get('voice_id') or v.get('id') or v.get('name')
            if not vid or vid in seen_ids:
                continue
            seen_ids.add(vid)
            # Non-destructive: only set provider if absent
            v.setdefault('provider', key)
            aggregated.append(v)

    return aggregated


def _install_voices_aggregation_patch() -> None:
    """Replace the GET /api/tts/voices route with an aggregating version.

    Walks app.routes, finds the matching APIRoute, and rebuilds its internal
    dispatcher (dependant + app) to point at our aggregating endpoint while
    preserving the original's login/rate-limit dependencies.
    """
    global _voices_patch_installed
    if _voices_patch_installed:
        return

    try:
        from core.api_fastapi import app
    except ImportError:
        logger.warning("[qwen3-tts] Could not import core.api_fastapi.app — voices aggregation skipped")
        return

    try:
        from core.auth import require_login
        from core.api_fastapi import get_system as _get_system
        from core.tts.utils import default_voice as _default_voice
    except ImportError as e:
        logger.warning(f"[qwen3-tts] voices aggregation — missing deps: {e}")
        return

    try:
        from fastapi import Depends
        from fastapi.routing import APIRoute
        from fastapi.dependencies.utils import get_dependant
        try:
            from fastapi.dependencies.utils import get_flat_dependant
        except ImportError:
            get_flat_dependant = None
    except ImportError as e:
        logger.warning(f"[qwen3-tts] voices aggregation — FastAPI imports failed: {e}")
        return

    # Endpoint preserves original signature so FastAPI's dep injection works.
    async def aggregating_voices_get(_=Depends(require_login), system=Depends(_get_system)):
        """List voices from ALL registered TTS providers (not just active)."""
        import asyncio
        import config as _cfg
        prov_name = getattr(_cfg, 'TTS_PROVIDER', 'none')
        provider = getattr(system.tts, 'provider', None) if system and getattr(system, 'tts', None) else None
        voices = await asyncio.to_thread(_aggregate_all_voices)
        return {
            "voices": voices,
            "provider": prov_name,
            "default_voice": _default_voice(prov_name),
            "speed_min": getattr(provider, 'SPEED_MIN', 0.5),
            "speed_max": getattr(provider, 'SPEED_MAX', 2.5),
        }

    # Find the matching route and rebuild it in place
    patched = False
    try:
        for route in app.routes:
            if not isinstance(route, APIRoute):
                continue
            path = getattr(route, 'path', None)
            methods = getattr(route, 'methods', None) or set()
            if path != '/api/tts/voices' or 'GET' not in methods:
                continue

            # Swap endpoint + rebuild dispatcher
            route.endpoint = aggregating_voices_get
            route.dependant = get_dependant(
                path=route.path_format,
                call=aggregating_voices_get,
                scope="function",
            )
            if get_flat_dependant is not None:
                try:
                    route._flat_dependant = get_flat_dependant(route.dependant)
                except Exception:
                    pass
            # Rebuild route.app — this is what Starlette actually calls.
            # get_route_handler() reads self.dependant and self.endpoint,
            # so after swapping those, rebuilding route.app picks them up.
            try:
                from fastapi.routing import request_response as _req_resp
                route.app = _req_resp(route.get_route_handler())
            except Exception as rebuild_err:
                logger.warning(f"[qwen3-tts] voices route.app rebuild failed: {rebuild_err}")
                # Still leave endpoint/dependant swapped — may work partially
            patched = True
            break
    except Exception as e:
        logger.warning(f"[qwen3-tts] voices aggregation patch walk failed: {e}")
        return

    if patched:
        _voices_patch_installed = True
        logger.info("[qwen3-tts] /api/tts/voices aggregation patch installed "
                    "(persona editor now shows voices from all TTS providers)")
    else:
        logger.warning("[qwen3-tts] /api/tts/voices route not found during patch walk "
                       "— persona editor dropdown will stay filtered to active provider")


# Install the aggregation patch. Core routes are registered at app startup
# BEFORE plugins load, so the route should be present when this fires.
_install_voices_aggregation_patch()


# ═══════════════════════════════════════════════════════════════════════════
# Layer B: Defensive per-speak guard (pre_tts hook)
# ═══════════════════════════════════════════════════════════════════════════

def pre_tts(event):
    """Cross-check TTS client voice/provider against the active persona.

    Runs on every TTS generation as a safety net. Reads the persona's voice
    from disk (authoritative) and syncs provider/voice/pitch/speed if the
    client has drifted out of alignment.
    """
    global _last_error_count

    try:
        logger.info("[qwen3-tts] Guard: FIRED — pre_tts hook executing")

        # Ensure Layer A patch is installed (idempotent)
        _install_validate_voice_patch()

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

        # ── Determine correct provider from voice ID (all 4 providers) ───
        current_voice = getattr(system.tts, 'voice_name', None) or ''
        current_provider = getattr(config, 'TTS_PROVIDER', 'none')
        target_provider = _target_provider_for_voice(persona_voice)
        needs_fix = False

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
