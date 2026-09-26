"""binary_sensor.calmneedle_alert - on when the score has dropped by >= threshold since reset."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import CalmNeedleConfigEntry
from .const import ATTRIBUTION, CONF_DROP_THRESHOLD, DEFAULT_DROP_THRESHOLD, DOMAIN
from .coordinator import CalmNeedleCoordinator
from .sensor import _device


async def async_setup_entry(
    hass: HomeAssistant, entry: CalmNeedleConfigEntry, add: AddEntitiesCallback
) -> None:
    if entry.runtime_data.client.linked:
        add([AlertBinarySensor(entry.runtime_data, entry.entry_id)])


class AlertBinarySensor(CoordinatorEntity[CalmNeedleCoordinator], BinarySensorEntity):
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

    @property
    def is_on(self) -> bool | None:
        cur = self._current
        if cur is None:
            return None
        if self.coordinator.last_reset_score is None:
            self.coordinator.last_reset_score = cur  # first reading is the reference
            return False
        return (self.coordinator.last_reset_score - cur) >= self._threshold

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        cur = self._current
        ref = self.coordinator.last_reset_score
        events = (self.coordinator.data or {}).get("scopes", {}).get(self.coordinator.primary_scope, {}).get("events") or []
        return {
            "threshold": self._threshold,
            "reference_score": ref,
            "drop": (ref - cur) if (ref is not None and cur is not None) else None,
            "top_event": events[0].get("title") if events else None,
            "note": "Call the calmneedle.reset_alert service (or reload the integration) to re-arm from the current score.",
        }

    async def async_reset(self) -> None:
        self.coordinator.last_reset_score = self._current
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Expose a simple entity service for re-arming.
        self.hass.services.async_register(DOMAIN, "reset_alert", self._handle_reset)

    async def _handle_reset(self, _call: Any) -> None:
        await self.async_reset()
