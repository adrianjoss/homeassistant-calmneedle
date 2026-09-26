"""binary_sensor.calmneedle_alert - on when the score has dropped by >= threshold since reset."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import CalmNeedleConfigEntry
from .const import ATTRIBUTION, CONF_DROP_THRESHOLD, DEFAULT_DROP_THRESHOLD
from .coordinator import CalmNeedleCoordinator
from .sensor import _device


async def async_setup_entry(
    hass: HomeAssistant, entry: CalmNeedleConfigEntry, add: AddEntitiesCallback
) -> None:
    if entry.runtime_data.client.linked:
        # Entity service (not a bare hass service): unloads cleanly and supports multiple
        # entries / targets (tester finding B7).
        platform = entity_platform.async_get_current_platform()
        platform.async_register_entity_service("reset_alert", None, "async_reset")
        add([AlertBinarySensor(entry.runtime_data, entry.entry_id)])


class AlertBinarySensor(CoordinatorEntity[CalmNeedleCoordinator], BinarySensorEntity, RestoreEntity):
    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION
    _attr_icon = "mdi:gauge-low"
    _attr_name = "Alert"

    def __init__(self, coord: CalmNeedleCoordinator, entry_id: str) -> None:
        super().__init__(coord)
        self._attr_unique_id = f"{entry_id}-alert"
        self._attr_suggested_object_id = "calmneedle_alert"
        self._attr_device_info = _device(entry_id)

    @property
    def _threshold(self) -> int:
        e = self.coordinator.entry
        return int(e.options.get(CONF_DROP_THRESHOLD, e.data.get(CONF_DROP_THRESHOLD, DEFAULT_DROP_THRESHOLD)))

    @property
    def _current(self) -> int | None:
        v = (self.coordinator.data or {}).get("scopes", {}).get(self.coordinator.primary_scope, {}).get("overall")
        return int(round(v)) if isinstance(v, (int, float)) else None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # The reference must survive restarts and reloads (tester finding B2): a drop that
        # spans a restart should still fire. Restore it from the last recorded state.
        if self.coordinator.last_reset_score is None:
            last = await self.async_get_last_state()
            ref = (last.attributes.get("reference_score") if last else None)
            if isinstance(ref, (int, float)):
                self.coordinator.last_reset_score = int(ref)
        self._seed_reference()

    def _seed_reference(self) -> None:
        if self.coordinator.last_reset_score is None and self._current is not None:
            self.coordinator.last_reset_score = self._current

    def _handle_coordinator_update(self) -> None:
        # State mutation belongs here, never in a property read (tester finding B3).
        self._seed_reference()
        super()._handle_coordinator_update()

    @property
    def is_on(self) -> bool | None:
        cur, ref = self._current, self.coordinator.last_reset_score
        if cur is None or ref is None:
            return None
        return (ref - cur) >= self._threshold

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        cur = self._current
        ref = self.coordinator.last_reset_score
        d = (self.coordinator.data or {}).get("scopes", {}).get(self.coordinator.primary_scope, {})
        events = d.get("events") or []
        return {
            "threshold": self._threshold,
            "reference_score": ref,
            "current_score": cur,
            "scope": self.coordinator.primary_scope,
            "band": d.get("band"),
            "drop": (ref - cur) if (ref is not None and cur is not None) else None,
            "top_event": events[0].get("title") if events else None,
        }

    async def async_reset(self) -> None:
        self.coordinator.last_reset_score = self._current
        self.async_write_ha_state()
