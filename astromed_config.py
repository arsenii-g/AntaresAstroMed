"""AstroMed configuration, with compatibility for existing Team Antares setups."""
import os
from pathlib import Path

PRODUCT_NAME = "AstroMed"
TEAM_NAME = "Team Antares"


def setting(name: str, default: str | None = None) -> str | None:
    """Prefer ASTROMED_*; accept the previous SPACEHEALTH_* environment names."""
    return os.environ.get(f"ASTROMED_{name}", os.environ.get(f"SPACEHEALTH_{name}", default))


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
