"""Sensors (spec 8.6): overall per scope, six categories, preparedness tier."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import CalmNeedleConfigEntry
from .const import ATTRIBUTION, CATEGORIES, CIVIL_UNREST_FOOTNOTE, DISCLAIMER, DOMAIN, SCOPES
from .coordinator import CalmNeedleCoordinator


def _device(entry_id: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry_id)},
        name="CalmNeedle",
        manufacturer="Migrations Limited",
        model="UK Stability Index",
        entry_type=DeviceEntryType.SERVICE,
        configuration_url="https://calmneedle.com/account/api",
    )


async def async_setup_entry(
    hass: HomeAssistant, entry: CalmNeedleConfigEntry, add: AddEntitiesCallback
) -> None:
    coord = entry.runtime_data
    entities: list[SensorEntity] = [ScoreSensor(coord, entry.entry_id, "uk")]
    if coord.client.linked:
        for scope in coord.scopes:
            if scope != "uk":
                entities.append(ScoreSensor(coord, entry.entry_id, scope))
        for cat in CATEGORIES:
            entities.append(CategorySensor(coord, entry.entry_id, cat))
        entities.append(PrepareTierSensor(coord, entry.entry_id))
    add(entities)


class _Base(CoordinatorEntity[CalmNeedleCoordinator]):
    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION
    _attr_icon = "mdi:gauge"

    def __init__(self, coord: CalmNeedleCoordinator, entry_id: str) -> None:
        super().__init__(coord)
        self._attr_device_info = _device(entry_id)

    def _scope_data(self, scope: str) -> dict[str, Any]:
        return (self.coordinator.data or {}).get("scopes", {}).get(scope) or {}

    @property
    def _primary(self) -> dict[str, Any]:
        return self._scope_data(self.coordinator.primary_scope)


class ScoreSensor(_Base, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = None
    _attr_suggested_display_precision = 0
    # Static or bulky attributes stay out of the recorder (tester finding B9).
    _unrecorded_attributes = frozenset(
        {"footnotes", "disclaimer", "events", "watchlist", "history_48h", "weights"}
    )

    def __init__(self, coord: CalmNeedleCoordinator, entry_id: str, scope: str) -> None:
        super().__init__(coord, entry_id)
        self._scope = scope
        self._attr_unique_id = f"{entry_id}-score-{scope}"
        self._attr_name = "UK" if scope == "uk" else SCOPES.get(scope, scope)

    @property
    def native_value(self) -> int | None:
        v = self._scope_data(self._scope).get("overall")
        return int(round(v)) if isinstance(v, (int, float)) else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self._scope_data(self._scope)
        attrs: dict[str, Any] = {
            "band": d.get("band"),
            "delta_24h": d.get("delta_24h"),
            "updated_at": d.get("updated_at"),
            "scope": self._scope,
            "footnotes": d.get("footnotes", []),
            "disclaimer": DISCLAIMER,
        }
        if "history" in d:  # free mode: 48 h hourly points
            attrs["history_48h"] = [p.get("overall") for p in d["history"]]
        if self.coordinator.client.linked:
            attrs["events"] = d.get("events", [])[:5]
            attrs["watchlist"] = d.get("watchlist", [])
            # Category weights explain why the overall is not a simple category average
            # (tester finding A7); published methodology data.
            attrs["weights"] = d.get("weights")
        else:
            attrs["tier"] = "free"
        return attrs


class CategorySensor(_Base, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0  # match the whole-number overall (tester finding A7)
    _unrecorded_attributes = frozenset({"footnote"})

    def __init__(self, coord: CalmNeedleCoordinator, entry_id: str, category: str) -> None:
        super().__init__(coord, entry_id)
        self._cat = category
        self._attr_unique_id = f"{entry_id}-cat-{category}"
        self._attr_name = category.replace("_", " ").title() + ("*" if category == "civil_unrest" else "")

    @property
    def native_value(self) -> float | None:
        c = self._primary.get("categories", {}).get(self._cat) or {}
        return c.get("score")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self._primary.get("categories", {}).get(self._cat) or {}
        attrs: dict[str, Any] = {
            "delta_24h": c.get("delta_24h"),
            "scope": self.coordinator.primary_scope,
            # Which region this category describes, spelled out (tester findings A5/B12).
            "region": SCOPES.get(self.coordinator.primary_scope, self.coordinator.primary_scope),
            "updated_at": self._primary.get("updated_at"),
        }
        if self._cat == "civil_unrest":
            attrs["footnote"] = CIVIL_UNREST_FOOTNOTE
            attrs["events_only"] = self._primary.get("civil_unrest_events_only")
            attrs["anger_level"] = (self._primary.get("anger") or {}).get("level")
        return attrs


PREPARE_TIERS = {0: "none", 1: "nudge", 2: "official_instruction"}


class PrepareTierSensor(_Base, SensorEntity):
    """Enum sensor (tester finding B11): dashboards and voice read "nudge", not a bare 1."""

    _attr_icon = "mdi:home-alert-outline"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(PREPARE_TIERS.values())
    _unrecorded_attributes = frozenset({"note"})

    def __init__(self, coord: CalmNeedleCoordinator, entry_id: str) -> None:
        super().__init__(coord, entry_id)
        self._attr_unique_id = f"{entry_id}-prepare-tier"
        self._attr_name = "Prepare tier"

    @property
    def native_value(self) -> str | None:
        v = self._primary.get("prepare_tier")
        return PREPARE_TIERS.get(int(v)) if v is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "tier_number": self._primary.get("prepare_tier"),
            "official_source_url": self._primary.get("prepare_source_url"),
            "scope": self.coordinator.primary_scope,
            "note": (
                "none = nothing active; nudge = official general guidance is highlighted; "
                "official_instruction = a government instruction is in force - the source link "
                "is in official_source_url."
            ),
        }
