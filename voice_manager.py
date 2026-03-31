"""Voice Manager — CRUD for saved Qwen3-TTS voice profiles.

Voices are organized by compatibility:
    voices/custom/  — Custom preset voices (speaker + instruction). Work on ANY model size.
    voices/0.6B/    — Clone & design voices created with the 0.6B model.
    voices/1.7B/    — Clone & design voices created with the 1.7B model.

Clone voices have model-specific cached embeddings (.pt) and cannot be used
across model sizes. Custom voices are just speaker name + text instructions,
so they're fully cross-compatible.

Audio references live in each directory's audio/ subfolder.
Built-in presets (Ryan, Serena, etc.) have no files — they're hardcoded.
"""
import json
import logging
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

VOICES_DIR = Path(__file__).parent / "voices"
VALID_MODEL_SIZES = ("0.6B", "1.7B")
DEFAULT_MODEL_SIZE = "0.6B"
CUSTOM_DIR_NAME = "custom"

# Voice types that are model-size-dependent (have embeddings/tensors)
MODEL_BOUND_TYPES = ("voice_clone", "voice_design")

# Built-in Qwen3-TTS preset speakers (CustomVoice models)
PRESET_SPEAKERS = [
    {"id": "aiden",    "name": "Aiden",    "category": "Male",   "description": "Calm, clear male voice"},
    {"id": "dylan",    "name": "Dylan",    "category": "Male",   "description": "Youthful male voice"},
    {"id": "eric",     "name": "Eric",     "category": "Male",   "description": "Mature, steady male voice"},
    {"id": "ono_anna", "name": "Ono_anna", "category": "Female", "description": "Gentle Japanese female voice"},
    {"id": "ryan",     "name": "Ryan",     "category": "Male",   "description": "Dynamic English male voice"},
    {"id": "serena",   "name": "Serena",   "category": "Female", "description": "Warm, clear female voice"},
    {"id": "sohee",    "name": "Sohee",    "category": "Female", "description": "Bright Korean female voice"},
    {"id": "uncle_fu", "name": "Uncle_fu", "category": "Male",   "description": "Seasoned, warm male voice"},
    {"id": "vivian",   "name": "Vivian",   "category": "Female", "description": "Bright, young female voice"},
]

SUPPORTED_LANGUAGES = [
    "Auto", "Chinese", "English", "Japanese", "Korean",
    "French", "German", "Spanish", "Portuguese", "Russian", "Italian"
]


def _slugify(name: str) -> str:
    """Convert a voice name to a safe filename slug."""
    slug = re.sub(r'[^a-zA-Z0-9_-]', '-', name.lower().strip())
    slug = re.sub(r'-+', '-', slug).strip('-')
    return slug or 'voice'


class VoiceProfile:
    """A saved voice configuration."""

    def __init__(self, data: dict):
        self.id: str = data.get("id", "")
        self.name: str = data.get("name", "Unnamed")
        self.type: str = data.get("type", "custom_voice")  # voice_design | voice_clone | custom_voice
        self.speaker: str = data.get("speaker", "")         # For custom_voice type
        self.instruct: str = data.get("instruct", "")       # Style/emotion instruction
        self.language: str = data.get("language", "Auto")
        self.model_size: str = data.get("model_size", "")   # Only set for clone/design voices
        self.ref_audio: str = data.get("ref_audio", "")     # Filename for clone ref audio
        self.ref_text: str = data.get("ref_text", "")       # Transcript for clone ref
        self.x_vector_only: bool = data.get("x_vector_only", False)
        self.prompt_path: str = data.get("prompt_path", "")  # Cached .pt voice clone prompt
        self.preview_audio: str = data.get("preview_audio", "")
        self.created: str = data.get("created", "")
        self.modified: str = data.get("modified", "")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "speaker": self.speaker,
            "instruct": self.instruct,
            "language": self.language,
            "model_size": self.model_size,
            "ref_audio": self.ref_audio,
            "ref_text": self.ref_text,
            "x_vector_only": self.x_vector_only,
            "prompt_path": self.prompt_path,
            "preview_audio": self.preview_audio,
            "created": self.created,
            "modified": self.modified,
        }


class VoiceManager:
    """Manages saved voice profiles on disk, organized by type and model size."""

    def __init__(self, voices_dir: Optional[Path] = None):
        self._dir = voices_dir or VOICES_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        # Create subdirectories
        for subdir in [CUSTOM_DIR_NAME] + list(VALID_MODEL_SIZES):
            d = self._dir / subdir
            d.mkdir(exist_ok=True)
            (d / "audio").mkdir(exist_ok=True)
        # Migrate any legacy voices from the flat directory
        self._migrate_legacy_voices()

    def _voice_dir(self, voice_type: str, model_size: str = "") -> Path:
        """Get the storage directory for a voice based on its type.

        Custom voices go in custom/, clone/design go in {model_size}/.
        """
        if voice_type not in MODEL_BOUND_TYPES:
            return self._dir / CUSTOM_DIR_NAME
        if model_size not in VALID_MODEL_SIZES:
            model_size = DEFAULT_MODEL_SIZE
        return self._dir / model_size

    def _all_voice_dirs(self) -> List[tuple]:
        """Return all (subdir_name, path) pairs that may contain voices."""
        dirs = [(CUSTOM_DIR_NAME, self._dir / CUSTOM_DIR_NAME)]
        for size in VALID_MODEL_SIZES:
            dirs.append((size, self._dir / size))
        return dirs

    def _migrate_legacy_voices(self):
        """Move voices from old flat layout to the new subdirectory structure."""
        legacy_audio_dir = self._dir / "audio"
        migrated = 0
        for f in self._dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                vtype = data.get("type", "custom_voice")
                model_size = data.get("model_size", DEFAULT_MODEL_SIZE)
                target_dir = self._voice_dir(vtype, model_size)
                target_audio_dir = target_dir / "audio"

                # Move the JSON profile
                target_json = target_dir / f.name
                if not target_json.exists():
                    shutil.move(str(f), str(target_json))
                    logger.info(f"[Qwen3-TTS] Migrated voice: {f.name} -> {target_dir.name}/")
                    migrated += 1

                # Move the cached .pt prompt if it exists (clone/design only)
                voice_id = data.get("id", "")
                pt_file = self._dir / f"{voice_id}.pt"
                if pt_file.exists():
                    target_pt = target_dir / pt_file.name
                    if not target_pt.exists():
                        shutil.move(str(pt_file), str(target_pt))
                        logger.info(f"[Qwen3-TTS] Migrated prompt: {pt_file.name} -> {target_dir.name}/")

                # Move associated audio files
                for audio_key in ("ref_audio", "preview_audio"):
                    audio_name = data.get(audio_key, "")
                    if audio_name and legacy_audio_dir.exists():
                        src = legacy_audio_dir / audio_name
                        if src.exists():
                            dst = target_audio_dir / audio_name
                            if not dst.exists():
                                shutil.move(str(src), str(dst))
                                logger.info(f"[Qwen3-TTS] Migrated audio: {audio_name} -> {target_dir.name}/audio/")
            except Exception as e:
                logger.warning(f"[Qwen3-TTS] Failed to migrate {f.name}: {e}")

        # Clean up empty legacy audio dir
        if legacy_audio_dir.exists():
            remaining = [f for f in legacy_audio_dir.glob("*") if f.name != '.gitkeep']
            if not remaining:
                shutil.rmtree(str(legacy_audio_dir), ignore_errors=True)

        if migrated:
            logger.info(f"[Qwen3-TTS] Migrated {migrated} voice(s) to subdirectories")

    def list_voices(self, model_size: Optional[str] = None) -> List[dict]:
        """List saved voice profiles.

        If model_size is given, returns only clone/design voices for that size
        plus all custom voices. If None, returns everything.
        """
        voices = []
        for subdir_name, subdir_path in self._all_voice_dirs():
            # If filtering by model_size, skip other model sizes (but always include custom)
            if model_size and subdir_name != CUSTOM_DIR_NAME and subdir_name != model_size:
                continue
            for f in sorted(subdir_path.glob("*.json")):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    # Ensure directory-based metadata is correct
                    if subdir_name in VALID_MODEL_SIZES:
                        data["model_size"] = subdir_name
                    voices.append(data)
                except Exception as e:
                    logger.warning(f"[Qwen3-TTS] Bad voice profile {f.name}: {e}")
        return voices

    def get_voice(self, voice_id: str) -> Optional[VoiceProfile]:
        """Get a voice profile by ID (searches all directories)."""
        for _, subdir_path in self._all_voice_dirs():
            path = subdir_path / f"{voice_id}.json"
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    return VoiceProfile(data)
                except Exception as e:
                    logger.error(f"[Qwen3-TTS] Failed to load voice {voice_id}: {e}")
                    return None
        return None

    def save_voice(self, data: dict) -> VoiceProfile:
        """Save or update a voice profile.

        Custom voices go to custom/, clone/design voices go to {model_size}/.
        If data has no 'id', generates one from the name.
        Returns the saved VoiceProfile.
        """
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        vtype = data.get("type", "custom_voice")
        model_size = data.get("model_size", DEFAULT_MODEL_SIZE)

        # Custom voices don't need model_size — clear it
        if vtype not in MODEL_BOUND_TYPES:
            data["model_size"] = ""
        else:
            if model_size not in VALID_MODEL_SIZES:
                model_size = DEFAULT_MODEL_SIZE
            data["model_size"] = model_size

        voice_id = data.get("id")
        if not voice_id:
            base_slug = _slugify(data.get("name", "voice"))
            voice_id = f"{base_slug}-{uuid.uuid4().hex[:6]}"
            data["id"] = voice_id
            data["created"] = now

        data["modified"] = now
        profile = VoiceProfile(data)

        target_dir = self._voice_dir(vtype, model_size)
        path = target_dir / f"{voice_id}.json"
        path.write_text(json.dumps(profile.to_dict(), indent=2), encoding="utf-8")
        logger.info(f"[Qwen3-TTS] Saved voice: {profile.name} ({voice_id}) in {target_dir.name}/")
        return profile

    def delete_voice(self, voice_id: str) -> bool:
        """Delete a voice profile and its associated audio files."""
        for subdir_name, subdir_path in self._all_voice_dirs():
            path = subdir_path / f"{voice_id}.json"
            if not path.exists():
                continue

            # Load profile to find associated files
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                audio_dir = subdir_path / "audio"
                for audio_key in ("ref_audio", "preview_audio"):
                    audio_file = data.get(audio_key, "")
                    if audio_file:
                        audio_path = audio_dir / audio_file
                        if audio_path.exists():
                            audio_path.unlink()
                # Delete cached voice clone prompt
                prompt_file = data.get("prompt_path", "")
                if prompt_file:
                    prompt_path = subdir_path / prompt_file
                    if prompt_path.exists():
                        prompt_path.unlink()
            except Exception:
                pass

            path.unlink()
            logger.info(f"[Qwen3-TTS] Deleted voice: {voice_id} from {subdir_name}/")
            return True
        return False

    def save_audio_file(self, audio_bytes: bytes, voice_type: str = "custom_voice",
                        model_size: str = DEFAULT_MODEL_SIZE,
                        prefix: str = "ref", ext: str = ".wav") -> str:
        """Save audio bytes to the appropriate audio directory, return the filename."""
        target_dir = self._voice_dir(voice_type, model_size)
        audio_dir = target_dir / "audio"
        audio_dir.mkdir(exist_ok=True)
        filename = f"{prefix}_{uuid.uuid4().hex[:8]}{ext}"
        path = audio_dir / filename
        path.write_bytes(audio_bytes)
        return filename

    def get_audio_path(self, filename: str) -> Optional[Path]:
        """Get the full path for an audio file, searching all directories."""
        for _, subdir_path in self._all_voice_dirs():
            path = subdir_path / "audio" / filename
            if path.exists():
                return path
        return None

    def get_voice_dir(self, voice_type: str, model_size: str = "") -> Path:
        """Get the directory path for a voice type/size (for .pt prompts, etc.)."""
        return self._voice_dir(voice_type, model_size)

    def get_all_for_provider(self) -> List[dict]:
        """Get all voices formatted for the TTS provider voice list.

        Returns a combined list of saved voices + preset speakers,
        formatted for the /api/tts/voices endpoint.

        Grouping in persona dropdown:
          - Custom Preset voices: "Qwen3-TTS (Custom Preset)" — no model size
          - Clone voices: "Qwen3-TTS 0.6B (Cloned)" or "Qwen3-TTS 1.7B (Cloned)"
          - Design voices: "Qwen3-TTS 1.7B (Designed)"
          - Built-in presets: "Qwen3-TTS (Preset Male/Female)"
        """
        voices = []

        for profile_data in self.list_voices():
            vtype = profile_data.get("type", "custom_voice")
            type_label = {
                "voice_design": "Designed",
                "voice_clone": "Cloned",
                "custom_voice": "Custom Preset",
            }.get(vtype, "Custom")

            model_size = profile_data.get("model_size", "")
            if vtype in MODEL_BOUND_TYPES and model_size:
                category = f"Qwen3-TTS {model_size} ({type_label})"
            else:
                category = f"Qwen3-TTS ({type_label})"

            voices.append({
                "voice_id": f"qwen3:{profile_data['id']}",
                "name": profile_data.get("name", "Unnamed"),
                "category": category,
                "description": profile_data.get("instruct", "") or profile_data.get("speaker", ""),
                "model_size": model_size,
            })

        # Built-in presets (work on both model sizes)
        for sp in PRESET_SPEAKERS:
            voices.append({
                "voice_id": f"qwen3:preset:{sp['id']}",
                "name": sp["name"],
                "category": f"Qwen3-TTS (Preset {sp['category']})",
                "description": sp["description"],
            })

        return voices


# Module-level singleton
voice_manager = VoiceManager()
