from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from homeassistant.helpers.translation import async_get_translations

from custom_components.energy_planner.const import (
    CONF_BATTERY_CAPACITY_ENTITY,
    CONF_BATTERY_MIN_SOC_ENTITY,
    CONF_BATTERY_SOC_ENTITY,
    CONF_CHARGE_WINDOW_END,
    CONF_CHARGE_WINDOW_START,
    CONF_FORECAST_HORIZON_HOURS,
    CONF_GRID_CHARGE_EFFICIENCY,
    CONF_GRID_CHARGE_MAX_KW,
    CONF_HISTORY_CORRECTION_PERCENT,
    CONF_HISTORY_LEARNING_DAYS,
    CONF_HOME_ENERGY_ENTITY,
    CONF_INTERVAL_MINUTES,
    CONF_MANAGED_ENERGY_ENTITIES,
    CONF_MIN_BASELINE_KWH_PER_HOUR,
    CONF_NT_WINDOW_1_END,
    CONF_NT_WINDOW_1_START,
    CONF_NT_WINDOW_2_END,
    CONF_NT_WINDOW_2_START,
    CONF_SOC_EPS_KWH,
    CONF_SOC_RESERVE_PERCENT,
    CONF_SOLCAST_ADDITIONAL_ENTITIES,
    CONF_SOLCAST_TODAY_ENTITY,
    CONF_SOLCAST_TOMORROW_ENTITY,
    CONF_SUN_START_REQUIRED_MINUTES,
    CONF_UPDATE_INTERVAL_MINUTES,
    DOMAIN,
)

TRANSLATION_DIR = (
    Path(__file__).parents[3] / "custom_components" / DOMAIN / "translations"
)
SUPPORTED_LANGUAGES = ("en", "cs", "sk")

CONFIG_FIELD_KEYS = {
    CONF_BATTERY_SOC_ENTITY,
    CONF_BATTERY_CAPACITY_ENTITY,
    CONF_BATTERY_MIN_SOC_ENTITY,
    CONF_HOME_ENERGY_ENTITY,
    CONF_MANAGED_ENERGY_ENTITIES,
    CONF_SOLCAST_TODAY_ENTITY,
    CONF_SOLCAST_TOMORROW_ENTITY,
    CONF_SOLCAST_ADDITIONAL_ENTITIES,
}
OPTION_FIELD_KEYS = {
    CONF_UPDATE_INTERVAL_MINUTES,
    CONF_HISTORY_LEARNING_DAYS,
    CONF_INTERVAL_MINUTES,
    CONF_HISTORY_CORRECTION_PERCENT,
    CONF_MIN_BASELINE_KWH_PER_HOUR,
    CONF_GRID_CHARGE_MAX_KW,
    CONF_GRID_CHARGE_EFFICIENCY,
    CONF_SOC_RESERVE_PERCENT,
    CONF_SOC_EPS_KWH,
    CONF_NT_WINDOW_1_START,
    CONF_NT_WINDOW_1_END,
    CONF_NT_WINDOW_2_START,
    CONF_NT_WINDOW_2_END,
    CONF_CHARGE_WINDOW_START,
    CONF_CHARGE_WINDOW_END,
    CONF_SUN_START_REQUIRED_MINUTES,
    CONF_FORECAST_HORIZON_HOURS,
}


def _load_translation(language: str) -> dict[str, Any]:
    return json.loads((TRANSLATION_DIR / f"{language}.json").read_text())


def _flatten(value: Mapping[str, Any], prefix: str = "") -> dict[str, str]:
    flattened: dict[str, str] = {}
    for key, nested_value in value.items():
        next_prefix = f"{prefix}.{key}" if prefix else key
        if isinstance(nested_value, Mapping):
            flattened.update(_flatten(nested_value, next_prefix))
        else:
            flattened[next_prefix] = str(nested_value)
    return flattened


def test_supported_translation_files_share_the_same_keys() -> None:
    expected_keys = set(_flatten(_load_translation("en")))

    assert expected_keys
    for language in SUPPORTED_LANGUAGES:
        assert set(_flatten(_load_translation(language))) == expected_keys


def test_config_and_options_fields_have_human_readable_labels() -> None:
    raw_keys = CONFIG_FIELD_KEYS | OPTION_FIELD_KEYS

    for language in SUPPORTED_LANGUAGES:
        translations = _flatten(_load_translation(language))
        labels = {
            translations[f"config.step.user.data.{key}"] for key in CONFIG_FIELD_KEYS
        } | {translations[f"options.step.init.data.{key}"] for key in OPTION_FIELD_KEYS}

        assert labels.isdisjoint(raw_keys)


async def test_home_assistant_loads_supported_config_flow_translations(hass) -> None:
    expected_battery_labels = {
        "en": "Battery state of charge",
        "cs": "Stav nabití baterie",
        "sk": "Stav nabitia batérie",
    }

    for language, expected_label in expected_battery_labels.items():
        translations = await async_get_translations(
            hass,
            language,
            "config",
            {DOMAIN},
            config_flow=True,
        )

        assert (
            translations[
                f"component.{DOMAIN}.config.step.user.data.{CONF_BATTERY_SOC_ENTITY}"
            ]
            == expected_label
        )


async def test_home_assistant_loads_supported_options_flow_translations(hass) -> None:
    expected_interval_labels = {
        "en": "Planning interval in minutes",
        "cs": "Interval plánování v minutách",
        "sk": "Interval plánovania v minútach",
    }

    for language, expected_label in expected_interval_labels.items():
        translations = await async_get_translations(
            hass,
            language,
            "options",
            {DOMAIN},
        )

        assert (
            translations[
                f"component.{DOMAIN}.options.step.init.data.{CONF_INTERVAL_MINUTES}"
            ]
            == expected_label
        )


async def test_home_assistant_loads_supported_binary_sensor_translations(
    hass,
) -> None:
    expected_charge_now_labels = {
        "en": "Charge now",
        "cs": "Nabíjet nyní",
        "sk": "Nabíjať teraz",
    }

    for language, expected_label in expected_charge_now_labels.items():
        translations = await async_get_translations(
            hass,
            language,
            "entity",
            {DOMAIN},
        )

        assert (
            translations[f"component.{DOMAIN}.entity.binary_sensor.charge_now.name"]
            == expected_label
        )


async def test_home_assistant_loads_supported_service_translations(hass) -> None:
    expected_recalculate_labels = {
        "en": "Recalculate",
        "cs": "Přepočítat",
        "sk": "Prepočítať",
    }

    for language, expected_label in expected_recalculate_labels.items():
        translations = await async_get_translations(
            hass,
            language,
            "services",
            {DOMAIN},
        )

        assert (
            translations[f"component.{DOMAIN}.services.recalculate.name"]
            == expected_label
        )


def test_custom_integration_does_not_ship_core_strings_file() -> None:
    assert not (TRANSLATION_DIR.parent / "strings.json").exists()
