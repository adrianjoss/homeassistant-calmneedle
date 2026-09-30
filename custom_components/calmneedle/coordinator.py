"""One coordinator, one request per cycle, all entities fed from it (spec 8.7)."""

from __future__ import annotations

import logging
import random
import time
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

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: CalmNeedleClient,
        store: Any | None = None,
    ) -> None:
        self.client = client
        self.entry = entry
        self._store = store
        self._failures = 0
        self._net_retries = 0  # quick-retry counter for failures that never reached the server
        self._last_ok: float | None = None  # monotonic time of the last successful poll
        self.last_reset_score: int | None = None  # for binary_sensor.calmneedle_alert
        self._reauth_prompted = False
        # A per-install jittered interval, kept for the life of the entry so installs stay
        # desynchronised (tester finding B13: resetting to a flat 15 min discarded the jitter).
        self._interval = SCAN_INTERVAL + timedelta(seconds=random.randint(0, STARTUP_JITTER_MAX_S))
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=self._interval)

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
            # ONE request per cycle whatever the scope list (tester finding B1): the server's
            # per-device budget is 6/hour and multi-scope answers arrive in a single call.
            states = await self.client.states(self.scopes)
            self._failures = 0
            self._net_retries = 0
            self._last_ok = time.monotonic()
            self.update_interval = self._interval  # restore after any backoff, keep the jitter
            data = {"scopes": states, "primary": self.primary_scope}
            await self._save_cache(data)
            if self.client.key_superseded_until and not self._reauth_prompted:
                # The key was rotated on the website; paired devices never see keys, so ask
                # for a re-link NOW while the old key still works (dies at the given time),
                # instead of a silent outage in 7 days (tester finding, 28 Sep 2026).
                self._reauth_prompted = True
                _LOGGER.warning(
                    "CalmNeedle key was rotated on the website; re-link before %s",
                    self.client.key_superseded_until,
                )
                self.entry.async_start_reauth(self.hass)
            return data
        except AuthError as err:
            # Revoked / suspended / rotated-out: prompt reconfiguration rather than retry forever.
            raise ConfigEntryAuthFailed(str(err)) from err
        except DeviceLimitError as err:
            raise ConfigEntryAuthFailed(
                "device_limit_reached: " + str(err)
            ) from err
        except RateLimitedError as err:
            # A 429 means "slow down", not "the data is bad" (tester finding B16): honour
            # Retry-After, keep the last good data over one short gap, and save the 15/30/60
            # ladder for real failures.
            self.update_interval = max(timedelta(seconds=err.retry_after), timedelta(minutes=1))
            _LOGGER.warning("CalmNeedle rate limited; retrying in %ss", err.retry_after)
            return self._grace_or_fail(f"rate limited, retry in {err.retry_after}s")
        except CalmNeedleError as err:
            self._backoff()
            return self._grace_or_fail(str(err))
        except OSError as err:
            # DNS stalls and failed connects never reached the server, so they spend none of
            # the request budget: retry quickly (twice) before falling back to the ladder
            # (tester finding, 30 Sep 2026 - a 2 s resolver blip cost 15 dark minutes).
            self._net_retries += 1
            if self._net_retries <= 2:
                self.update_interval = timedelta(seconds=90)
                _LOGGER.warning(
                    "CalmNeedle poll never left the house (%s); quick retry in 90 s", err
                )
            else:
                self._backoff()
            return self._grace_or_fail(f"network: {err}")
        except Exception as err:  # noqa: BLE001 - anything else unexpected
            self._backoff()
            return self._grace_or_fail(f"request failed: {err}")

    def _grace_or_fail(self, reason: str) -> dict[str, Any]:
        """Keep the last good data through short outages (tester finding, 30 Sep 2026).

        A 15-minute-old score is still a score; "unavailable" is louder than one failed poll
        deserves. Entities only go unavailable once the data is older than two poll intervals.
        """
        fresh_enough = (
            self.data is not None
            and self._last_ok is not None
            and time.monotonic() - self._last_ok < 2 * self._interval.total_seconds()
        )
        if fresh_enough:
            _LOGGER.warning("CalmNeedle poll failed (%s); keeping last good data", reason)
            return self.data
        raise UpdateFailed(reason)

    async def _save_cache(self, data: dict[str, Any]) -> None:
        """Persist the last good payload so a restart can skip its startup request (B13/#3)."""
        if self._store is not None:
            await self._store.async_save({"ts": time.time(), "data": data})

    def _backoff(self) -> None:
        """15 -> 30 -> 60 min, capped; entities go unavailable via UpdateFailed (8.7)."""
        self._failures += 1
        minutes = BACKOFF_STEPS[min(self._failures, len(BACKOFF_STEPS)) - 1]
        self.update_interval = timedelta(minutes=minutes)
        _LOGGER.warning("CalmNeedle poll failed (%d in a row); next try in %d min", self._failures, minutes)
