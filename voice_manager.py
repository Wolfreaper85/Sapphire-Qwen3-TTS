"""Voice Manager — CRUD for saved Qwen3-TTS voice profiles.

Each voice is a JSON file in the voices/ directory with metadata about how
to reproduce it (design description, clone reference, or preset speaker).
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
        self.model_size: str = data.get("model_size", "1.7B")
        self.ref_audio: str = data.get("ref_audio", "")     # Filename for clone ref audio
        self.ref_text: str = data.get("ref_text", "")       # Transcript for clone ref
        self.x_vector_only: bool = data.get("x_vector_only", False)
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
            "preview_audio": self.preview_audio,
            "created": self.created,
            "modified": self.modified,
        }


class VoiceManager:
    """Manages saved voice profiles on disk."""

    def __init__(self, voices_dir: Optional[Path] = None):
        self._dir = voices_dir or VOICES_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._audio_dir = self._dir / "audio"
        self._audio_dir.mkdir(exist_ok=True)

    def list_voices(self) -> List[dict]:
        """List all saved voice profiles."""
        voices = []
        for f in sorted(self._dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                voices.append(data)
            except Exception as e:
                logger.warning(f"[Qwen3-TTS] Bad voice profile {f.name}: {e}")
        return voices

    def get_voice(self, voice_id: str) -> Optional[VoiceProfile]:
        """Get a voice profile by ID."""
        path = self._dir / f"{voice_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return VoiceProfile(data)
        except Exception as e:
            logger.error(f"[Qwen3-TTS] Failed to load voice {voice_id}: {e}")
            return None

    def save_voice(self, data: dict) -> VoiceProfile:
        """Save or update a voice profile.

        If data has no 'id', generates one from the name.
        Returns the saved VoiceProfile.
        """
        now = time.strftime("%Y-%m-%d %H:%M:%S")

        voice_id = data.get("id")
        if not voice_id:
            base_slug = _slugify(data.get("name", "voice"))
            voice_id = f"{base_slug}-{uuid.uuid4().hex[:6]}"
            data["id"] = voice_id
            data["created"] = now

        data["modified"] = now
        profile = VoiceProfile(data)

        path = self._dir / f"{voice_id}.json"
        path.write_text(json.dumps(profile.to_dict(), indent=2), encoding="utf-8")
        logger.info(f"[Qwen3-TTS] Saved voice profile: {profile.name} ({voice_id})")
        return profile

    def delete_voice(self, voice_id: str) -> bool:
        """Delete a voice profile and its associated audio files."""
        path = self._dir / f"{voice_id}.json"
        if not path.exists():
            return False

        # Load profile to find associated audio files
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for audio_key in ("ref_audio", "preview_audio"):
                audio_file = data.get(audio_key, "")
                if audio_file:
                    audio_path = self._audio_dir / audio_file
                    if audio_path.exists():
                        audio_path.unlink()
        except Exception:
            pass

        path.unlink()
        logger.info(f"[Qwen3-TTS] Deleted voice profile: {voice_id}")
        return True

    def save_audio_file(self, audio_bytes: bytes, prefix: str = "ref", ext: str = ".wav") -> str:
        """Save audio bytes to the audio directory, return the filename."""
        filename = f"{prefix}_{uuid.uuid4().hex[:8]}{ext}"
        path = self._audio_dir / filename
        path.write_bytes(audio_bytes)
        return filename

    def get_audio_path(self, filename: str) -> Optional[Path]:
        """Get the full path for an audio file, if it exists."""
        path = self._audio_dir / filename
        if path.exists():
            return path
        return None

    def get_all_for_provider(self) -> List[dict]:
        """Get all voices formatted for the TTS provider voice list.

        Returns a combined list of saved voices + preset speakers,
        formatted for the /api/tts/voices endpoint.
        """
        voices = []

        # Saved custom voices first
        for profile_data in self.list_voices():
            vtype = profile_data.get("type", "custom_voice")
            type_label = {
                "voice_design": "Designed",
                "voice_clone": "Cloned",
                "custom_voice": "Custom Preset",
            }.get(vtype, "Custom")

            voices.append({
                "voice_id": f"qwen3:{profile_data['id']}",
                "name": profile_data.get("name", "Unnamed"),
                "category": f"Qwen3-TTS ({type_label})",
                "description": profile_data.get("instruct", "") or profile_data.get("speaker", ""),
            })

        # Built-in presets
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
