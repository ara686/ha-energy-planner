from __future__ import annotations

import json
from pathlib import Path

MANIFEST_PATH = (
    Path(__file__).parents[3] / "custom_components" / "energy_planner" / "manifest.json"
)


def test_manifest_declares_calculated_helper_integration() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text())

    assert manifest["integration_type"] == "helper"
    assert manifest["iot_class"] == "calculated"
