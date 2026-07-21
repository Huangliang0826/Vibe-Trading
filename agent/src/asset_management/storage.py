"""Persistent latest-plan storage for asset management."""

from __future__ import annotations

from pathlib import Path

from src.asset_management.models import AssetManagementPlan
from src.config.paths import get_runtime_root


class AssetManagementStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (get_runtime_root() / "asset_management" / "latest.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def get_latest(self) -> AssetManagementPlan | None:
        if not self.path.exists():
            return None
        try:
            return AssetManagementPlan.model_validate_json(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def save_latest(self, plan: AssetManagementPlan) -> AssetManagementPlan:
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(self.path)
        return plan
