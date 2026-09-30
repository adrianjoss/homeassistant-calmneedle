"""Thin async client for the CalmNeedle API. No Home Assistant imports, so it is unit-testable.

Free mode hits the public endpoints (no key). Linked mode sends the key plus the install id
(spec 5.2) and honours ETags (7.4). Errors are typed so the coordinator can back off correctly.
"""

from __future__ import annotations

import asyncio
from typing import Any

from .const import DEFAULT_BASE_URL, INSTALL_HEADER

USER_AGENT = "homeassistant-calmneedle/1.0.5 (+https://calmneedle.com)"


class CalmNeedleError(Exception):
    """Base error."""


class AuthError(CalmNeedleError):
    """Key invalid, revoked, or suspended (401 / 403 device_revoked)."""


class DeviceLimitError(CalmNeedleError):
    """Spec 5.4: the account already has ten devices."""

    def __init__(self, message: str, devices: list[dict[str, Any]]) -> None:
        super().__init__(message)
        self.devices = devices


class RateLimitedError(CalmNeedleError):
    def __init__(self, retry_after: int) -> None:
        super().__init__(f"rate limited; retry after {retry_after}s")
        self.retry_after = retry_after


class PairingExpired(CalmNeedleError):
    """Pairing code expired or already used (410)."""


class CalmNeedleClient:
    def __init__(
        self,
        session: Any,
        *,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str | None = None,
        install_id: str | None = None,
    ) -> None:
        self._session = session
        self._base = base_url.rstrip("/")
        self._key = api_key
        self._install = install_id
        self._etag: dict[str, str] = {}
        self._cache: dict[str, dict[str, Any]] = {}
        # Set from X-CalmNeedle-Key-Superseded: this key was rotated out on the website and
        # dies at the given ISO time; the integration should prompt a re-link now, while the
        # old key still works (tester finding, 28 Sep 2026).
        self.key_superseded_until: str | None = None

    @property
    def linked(self) -> bool:
        return bool(self._key)

    def _headers(self, keyed: bool) -> dict[str, str]:
        h = {"Accept": "application/json", "User-Agent": USER_AGENT}
        if keyed and self._key:
            h["Authorization"] = f"Bearer {self._key}"
            if self._install:
                h[INSTALL_HEADER] = self._install
        return h

    async def _get(self, path: str, *, keyed: bool) -> dict[str, Any]:
        url = f"{self._base}/api/v1{path}"
        headers = self._headers(keyed)
        if path in self._etag:
            headers["If-None-Match"] = self._etag[path]
        async with self._session.get(url, headers=headers, timeout=20) as resp:
            if keyed:
                self.key_superseded_until = resp.headers.get("X-CalmNeedle-Key-Superseded")
            if resp.status == 304 and path in self._cache:
                return self._cache[path]
            if resp.status == 429:
                raise RateLimitedError(int(resp.headers.get("Retry-After", "600")))
            body = await resp.json(content_type=None)
            if resp.status == 403 and body.get("error") == "device_limit_reached":
                raise DeviceLimitError(body.get("message", ""), body.get("devices", []))
            if resp.status in (401, 403):
                raise AuthError(body.get("error", "unauthorised"))
            if resp.status >= 400:
                raise CalmNeedleError(f"{resp.status}: {body.get('error', 'error')}")
            etag = resp.headers.get("ETag")
            if etag:
                self._etag[path] = etag
                self._cache[path] = body
            return body

    async def _post(self, path: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        async with self._session.post(
            f"{self._base}/api/v1{path}", json=payload, headers=self._headers(False), timeout=20
        ) as resp:
            if resp.status == 429:
                raise RateLimitedError(int(resp.headers.get("Retry-After", "600")))
            try:
                body = await resp.json(content_type=None)
            except Exception:  # noqa: BLE001 - 202/410 may carry no body
                body = {}
            return resp.status, body or {}

    # --- data ---------------------------------------------------------------------------------

    async def free_state(self) -> dict[str, Any]:
        score = await self._get("/score", keyed=False)
        hist = await self._get("/score/history?hours=48", keyed=False)
        return {**score, "history": hist.get("points", []), "locked": True}

    async def state(self, scope: str = "uk") -> dict[str, Any]:
        if not self.linked:
            return await self.free_state()
        return await self._get(f"/integration/state?scope={scope}", keyed=True)

    async def states(self, scopes: list[str]) -> dict[str, dict[str, Any]]:
        """All scopes in ONE request (?scopes=a,b) - the device budget is 6 requests/hour,
        so a 15-minute cycle must never cost more than one request (tester finding B1)."""
        if not self.linked:
            return {"uk": await self.free_state()}
        joined = ",".join(scopes)
        body = await self._get(f"/integration/state?scopes={joined}", keyed=True)
        return body.get("scopes", {})

    async def devices(self) -> dict[str, Any]:
        return await self._get("/integration/devices", keyed=True)

    # --- pairing (8.4) ------------------------------------------------------------------------

    async def pair_start(self, install_id: str) -> dict[str, Any]:
        status, body = await self._post("/integration/pair/start", {"install_id": install_id})
        if status >= 400:
            raise CalmNeedleError(body.get("error", "pair_start_failed"))
        return body

    async def pair_poll(self, code: str, poll_token: str) -> str | None:
        """Returns the key when approved, None while pending. Raises PairingExpired on 410."""
        status, body = await self._post(
            "/integration/pair/poll", {"code": code, "poll_token": poll_token}
        )
        if status == 202:
            return None
        if status == 410:
            raise PairingExpired()
        if status >= 400:
            raise CalmNeedleError(body.get("error", "pair_poll_failed"))
        return body["api_key"]

    async def wait_for_pairing(
        self, code: str, poll_token: str, *, interval: float = 3.0, timeout: float = 600
    ) -> str:
        waited = 0.0
        while waited < timeout:
            key = await self.pair_poll(code, poll_token)
            if key:
                return key
            await asyncio.sleep(interval)
            waited += interval
        raise PairingExpired()
