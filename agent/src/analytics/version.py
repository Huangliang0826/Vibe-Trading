from __future__ import annotations

import json
import re
from pathlib import Path


def read_app_version(repo_root: Path) -> str:
    try:
        value = json.loads((repo_root / "frontend" / "package.json").read_text(encoding="utf-8")).get("version")
    except (OSError, ValueError, AttributeError):
        return "unknown"
    return value if isinstance(value, str) and re.fullmatch(r"\d+\.\d+\.\d+", value) else "unknown"
