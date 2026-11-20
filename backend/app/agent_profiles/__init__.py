"""Server-owned profiles; callers supply IDs, never file paths."""

from pathlib import Path
from types import MappingProxyType

PROFILES = MappingProxyType({
    "FootballAnalysisExpert": Path(__file__).with_name("FootballAnalysisExpert.md"),
})


def load_profile(profile_id: str) -> str:
    try:
        path = PROFILES[profile_id]
    except (KeyError, TypeError):
        raise ValueError("Unknown Agent profile") from None
    return path.read_text(encoding="utf-8")
