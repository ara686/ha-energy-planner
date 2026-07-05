from __future__ import annotations

import json
from pathlib import Path

MANIFEST_PATH = (
    Path(__file__).parents[3] / "custom_components" / "energy_planner" / "manifest.json"
)
REPOSITORY_ROOT = Path(__file__).parents[3]


def test_manifest_declares_calculated_hub_integration() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text())

    assert manifest["integration_type"] == "hub"
    assert manifest["iot_class"] == "calculated"


def test_repository_includes_license_for_hacs_validation() -> None:
    license_text = (REPOSITORY_ROOT / "LICENSE").read_text()

    assert license_text.startswith("MIT License")
