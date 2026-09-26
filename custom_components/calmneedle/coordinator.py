"""One coordinator, one request per cycle, all entities fed from it (spec 8.7)."""

from __future__ import annotations

import logging
import random
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AuthError, CalmNeedleClient, CalmNeedleError, DeviceLimitError, RateLimitedError
from .const import (
    BACKOFF_STEPS,
    CONF_EXTRA_REGIONS,
    CONF_HOME_REGION,
    DOMAIN,
    SCAN_INTERVAL,
    STARTUP_JITTER_MAX_S,
)

_LOGGER = logging.getLogger(__name__)


class CalmNeedleCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls /integration/state for the home region (or UK) plus any extra regions.

    data = {"scopes": {scope: state_payload}, "primary": scope}
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: CalmNeedleClient) -> None:
        self.client = client
        self.entry = entry
        self._failures = 0
        self.last_reset_score: int | None = None  # for binary_sensor.calmneedle_alert
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL
            + timedelta(seconds=random.randint(0, STARTUP_JITTER_MAX_S)),
        )

    @property
    def primary_scope(self) -> str:
        return self.entry.options.get(CONF_HOME_REGION) or self.entry.data.get(CONF_HOME_REGION) or "uk"

    @property
    def scopes(self) -> list[str]:
        extra = self.entry.options.get(CONF_EXTRA_REGIONS) or self.entry.data.get(CONF_EXTRA_REGIONS) or []
        out = [self.primary_scope]
        if self.client.linked and "uk" not in out:
            out.append("uk")
        for s in extra:
            if s not in out:
                out.append(s)
        return out if self.client.linked else ["uk"]

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            states: dict[str, Any] = {}
            for scope in self.scopes:
                states[scope] = await self.client.state(scope)
            self._failures = 0
            self.update_interval = SCAN_INTERVAL  # jitter only on the first poll
            return {"scopes": states, "primary": self.primary_scope}
        except AuthError as err:
            # Revoked / suspended / rotated-out: prompt reconfiguration rather than retry forever.
            raise ConfigEntryAuthFailed(str(err)) from err
        except DeviceLimitError as err:
            raise ConfigEntryAuthFailed(
                "device_limit_reached: " + str(err)
            ) from err
        except RateLimitedError as err:
            self._backoff()
            raise UpdateFailed(f"rate limited, retry in {err.retry_after}s") from err
        except CalmNeedleError as err:
            self._backoff()
            raise UpdateFailed(str(err)) from err
        except Exception as err:  # noqa: BLE001 - network errors etc.
            self._backoff()
            raise UpdateFailed(f"request failed: {err}") from err

    def _backoff(self) -> None:
        """15 -> 30 -> 60 min, capped; entities go unavailable via UpdateFailed (8.7)."""
        self._failures += 1
        minutes = BACKOFF_STEPS[min(self._failures, len(BACKOFF_STEPS)) - 1]
        self.update_interval = timedelta(minutes=minutes)
        _LOGGER.warning("CalmNeedle poll failed (%d in a row); next try in %d min", self._failures, minutes)
