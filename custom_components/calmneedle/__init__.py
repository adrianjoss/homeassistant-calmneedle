"""CalmNeedle - UK stability index as Home Assistant entities (specs/05 section 8)."""

from __future__ import annotations

import time

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .api import CalmNeedleClient
from .const import CONF_API_KEY, CONF_INSTALL_ID, DEFAULT_BASE_URL, DOMAIN, SCAN_INTERVAL
from .coordinator import CalmNeedleCoordinator

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]

type CalmNeedleConfigEntry = ConfigEntry[CalmNeedleCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: CalmNeedleConfigEntry) -> bool:
    client = CalmNeedleClient(
        async_get_clientsession(hass),
        base_url=entry.data.get("base_url", DEFAULT_BASE_URL),
        api_key=entry.data.get(CONF_API_KEY),
        install_id=entry.data.get(CONF_INSTALL_ID),
    )
    store: Store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")
    coordinator = CalmNeedleCoordinator(hass, entry, client, store=store)
    # Restarts and reloads reuse the last payload if it is fresher than one cycle and covers
    # every configured scope (tester follow-up #3): the request budget is 6/hour, and two
    # reloads in an hour must not eat a third of it. A new region still forces a fetch.
    cached = await store.async_load()
    if (
        cached
        and time.time() - cached.get("ts", 0) < SCAN_INTERVAL.total_seconds()
        and set((cached.get("data") or {}).get("scopes", {})) >= set(coordinator.scopes)
    ):
        coordinator.async_set_updated_data(cached["data"])
    else:
        await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: CalmNeedleConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: CalmNeedleConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


__all__ = ["DOMAIN", "async_setup_entry", "async_unload_entry"]
