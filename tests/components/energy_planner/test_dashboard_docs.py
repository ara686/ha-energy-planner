from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from homeassistant.helpers.template import Template
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


@pytest.mark.parametrize(
    "title,gas_text", [("Plán ohřevu TUV", "**plyn**"), ("Hot-water plan", "**Gas**")]
)
@pytest.mark.parametrize(
    "available,recommended", [(True, True), (True, False), (False, None), (True, None)]
)
async def test_water_card_renders_gas_only_for_confirmed_recommendation(
    hass, title, gas_text, available, recommended
):
    card = next(
        card
        for card in _yaml_blocks(_DASHBOARD_DOC.read_text())
        if card.get("title") == title
    )
    attributes = {
        "forecast_complete": recommended is not None,
        "minimum_shortfall_kwh": 1.2,
        "alternative_heating_recommended": recommended,
    }
    hass.states.async_set(
        card["entity_id"], "0" if available else "unavailable", attributes
    )
    rendered = Template(card["content"], hass).async_render(parse_result=False)
    assert (gas_text in rendered) is (available and recommended is True)
