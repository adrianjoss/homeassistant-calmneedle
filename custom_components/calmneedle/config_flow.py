"""Config flow (spec 8.3 / 8.4): Continue free, or Link account with a six-character pairing code.

The user never sees or types the API key. HA shows the code, the user approves it at
calmneedle.com/link, HA polls and receives the key; the device is bound in the same step.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import CalmNeedleClient, CalmNeedleError, DeviceLimitError, PairingExpired, RateLimitedError
from .const import (
    CONF_API_KEY,
    CONF_DROP_THRESHOLD,
    CONF_EXTRA_REGIONS,
    CONF_HOME_REGION,
    CONF_INSTALL_ID,
    CONF_MODE,
    DEFAULT_BASE_URL,
    DEFAULT_DROP_THRESHOLD,
    DOMAIN,
    MODE_FREE,
    MODE_LINKED,
    SCOPES,
)

REGION_OPTIONS = [SelectOptionDict(value=k, label=v) for k, v in SCOPES.items()]


class CalmNeedleConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._install_id = str(uuid.uuid4())  # random, disposable, never a hardware id (5.5)
        self._code: str | None = None
        self._poll_token: str | None = None
        self._link_url: str = f"{DEFAULT_BASE_URL}/link"
        self._api_key: str | None = None
        self._poll_task: asyncio.Task | None = None
        self._poll_error: str | None = None

    def _client(self) -> CalmNeedleClient:
        return CalmNeedleClient(async_get_clientsession(self.hass), install_id=self._install_id)

    # --- step 1: free or linked ---------------------------------------------------------------

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            if user_input[CONF_MODE] == MODE_FREE:
                await self.async_set_unique_id(f"{DOMAIN}-free")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="CalmNeedle (free)",
                    data={CONF_MODE: MODE_FREE, CONF_HOME_REGION: "uk"},
                )
            return await self.async_step_pair()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MODE, default=MODE_LINKED): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value=MODE_LINKED, label="Link my CalmNeedle account (subscriber)"),
                                SelectOptionDict(value=MODE_FREE, label="Continue free (overall score only)"),
                            ],
                            mode=SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )

    # --- step 2: pairing code (8.4) -----------------------------------------------------------

    async def async_step_pair(self, user_input: dict[str, Any] | None = None):
        client = self._client()
        if self._code is None:
            try:
                start = await client.pair_start(self._install_id)
            except RateLimitedError:
                return self.async_abort(reason="rate_limited")
            except CalmNeedleError:
                return self.async_abort(reason="cannot_connect")
            self._code = start["code"]
            self._poll_token = start["poll_token"]
            self._link_url = start.get("link_url", self._link_url)
            self._poll_task = self.hass.async_create_task(self._poll_for_key(client))

        if self._api_key is not None:
            return await self.async_step_region()
        if self._poll_error is not None:
            reason, self._poll_error, self._code = self._poll_error, None, None
            return self.async_abort(reason=reason)
        # Show the code; the form's submit button re-enters this step and checks progress.
        return self.async_show_form(
            step_id="pair",
            description_placeholders={"code": self._code, "link_url": self._link_url},
            errors={"base": "pending"} if user_input is not None else None,
        )

    async def _poll_for_key(self, client: CalmNeedleClient) -> None:
        try:
            self._api_key = await client.wait_for_pairing(self._code or "", self._poll_token or "")
        except PairingExpired:
            self._poll_error = "pairing_expired"
        except DeviceLimitError:
            self._poll_error = "device_limit_reached"
        except CalmNeedleError:
            self._poll_error = "cannot_connect"

    # --- step 3: home region (subscriber) -----------------------------------------------------

    async def async_step_region(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            await self.async_set_unique_id(f"{DOMAIN}-{self._install_id}")
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=f"CalmNeedle ({SCOPES[user_input[CONF_HOME_REGION]]})",
                data={
                    CONF_MODE: MODE_LINKED,
                    CONF_API_KEY: self._api_key,
                    CONF_INSTALL_ID: self._install_id,
                    CONF_HOME_REGION: user_input[CONF_HOME_REGION],
                    CONF_EXTRA_REGIONS: user_input.get(CONF_EXTRA_REGIONS, []),
                    CONF_DROP_THRESHOLD: int(user_input.get(CONF_DROP_THRESHOLD, DEFAULT_DROP_THRESHOLD)),
                },
            )
        return self.async_show_form(step_id="region", data_schema=_region_schema())

    # --- reauth (revoked / rotated / limit) ---------------------------------------------------

    async def async_step_reauth(self, entry_data: dict[str, Any]):
        self._code = None
        self._api_key = None
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None):
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm")
        return await self.async_step_pair()

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return CalmNeedleOptionsFlow()


def _region_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    d = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_HOME_REGION, default=d.get(CONF_HOME_REGION, "uk")): SelectSelector(
                SelectSelectorConfig(options=REGION_OPTIONS, mode=SelectSelectorMode.DROPDOWN)
            ),
            vol.Optional(CONF_EXTRA_REGIONS, default=d.get(CONF_EXTRA_REGIONS, [])): SelectSelector(
                SelectSelectorConfig(options=REGION_OPTIONS, multiple=True, mode=SelectSelectorMode.DROPDOWN)
            ),
            vol.Optional(
                CONF_DROP_THRESHOLD, default=d.get(CONF_DROP_THRESHOLD, DEFAULT_DROP_THRESHOLD)
            ): NumberSelector(NumberSelectorConfig(min=1, max=30, step=1)),
        }
    )


class CalmNeedleOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if self.config_entry.data.get(CONF_MODE) == MODE_FREE:
            return self.async_abort(reason="free_no_options")
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(step_id="init", data_schema=_region_schema(current))
