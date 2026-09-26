"""Sensors (spec 8.6): overall per scope, six categories, preparedness tier."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
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

    def __init__(self, coord: CalmNeedleCoordinator, entry_id: str, scope: str) -> None:
        super().__init__(coord, entry_id)
        self._scope = scope
        self._attr_unique_id = f"{entry_id}-score-{scope}"
        self._attr_name = "UK" if scope == "uk" else SCOPES.get(scope, scope)
        self._attr_suggested_object_id = f"calmneedle_{scope.replace('-', '_')}"

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
        else:
            attrs["tier"] = "free"
        return attrs


class CategorySensor(_Base, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coord: CalmNeedleCoordinator, entry_id: str, category: str) -> None:
        super().__init__(coord, entry_id)
        self._cat = category
        self._attr_unique_id = f"{entry_id}-cat-{category}"
        self._attr_name = category.replace("_", " ").title() + ("*" if category == "civil_unrest" else "")
        self._attr_suggested_object_id = f"calmneedle_{category}"

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
            "updated_at": self._primary.get("updated_at"),
        }
        if self._cat == "civil_unrest":
            attrs["footnote"] = CIVIL_UNREST_FOOTNOTE
            attrs["events_only"] = self._primary.get("civil_unrest_events_only")
            attrs["anger_level"] = (self._primary.get("anger") or {}).get("level")
        return attrs


class PrepareTierSensor(_Base, SensorEntity):
    _attr_icon = "mdi:home-alert-outline"

    def __init__(self, coord: CalmNeedleCoordinator, entry_id: str) -> None:
        super().__init__(coord, entry_id)
        self._attr_unique_id = f"{entry_id}-prepare-tier"
        self._attr_name = "Prepare tier"
        self._attr_suggested_object_id = "calmneedle_prepare_tier"

    @property
    def native_value(self) -> int | None:
        v = self._primary.get("prepare_tier")
        return int(v) if v is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "official_source_url": self._primary.get("prepare_source_url"),
            "scope": self.coordinator.primary_scope,
            "note": "0 = nothing active; 1 = a quiet nudge; 2 = an official instruction is in force.",
        }
