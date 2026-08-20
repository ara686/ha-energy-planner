from __future__ import annotations

from pathlib import Path

import yaml
from jinja2 import Environment

_DASHBOARD_DOC = Path(__file__).parents[3] / "docs" / "dashboard.md"
_FENCE = "`" * 3


def test_managed_load_markdown_cards_are_valid_yaml_and_jinja():
    cards = {
        card["title"]: card
        for card in _yaml_blocks(_DASHBOARD_DOC.read_text())
        if card.get("type") == "markdown"
    }

    expected_titles = {
        "Plán ohřevu TUV",
        "Hot-water plan",
        "Plán nabíjení EV",
        "EV charging plan",
        "Energetický plán domácnosti",
        "Household energy plan",
    }
    assert expected_titles <= cards.keys()
    for title in expected_titles:
        card = cards[title]
        assert card["entity_id"]
        Environment().parse(card["content"])


def _yaml_blocks(document: str) -> list[dict]:
    return [
        yaml.safe_load(part.split(_FENCE, 1)[0])
        for part in document.split(f"{_FENCE}yaml\n")[1:]
    ]
