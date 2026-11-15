"""AstroMed configuration, with compatibility for existing Team Antares setups."""
import os
from pathlib import Path

PRODUCT_NAME = "AstroMed"
TEAM_NAME = "Team Antares"


def setting(name: str, default: str | None = None) -> str | None:
    """Prefer ASTROMED_*; accept the previous SPACEHEALTH_* environment names."""
    for prefix in ("ASTROMED", "SPACEHEALTH"):
        value = os.environ.get(f"{prefix}_{name}")
        if value:          # an empty variable counts as unset
            return value
    return default


def demo_mode() -> bool:
    return setting("DEMO") == "1"


def database_url() -> str:
    """Reuse an existing database; name new installations after AstroMed."""
    configured = setting("DATABASE_URL")
    if configured is not None:
        return configured
    # Preserve the team's recorded sensor data without moving or renaming files.
    filename = "spacehealth.db" if Path("spacehealth.db").exists() else "astromed.db"
    return f"sqlite:///./{filename}"
