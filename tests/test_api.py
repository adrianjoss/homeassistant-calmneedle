"""Client tests with a fake aiohttp session - no Home Assistant needed.

Run: python -m pytest homeassistant-calmneedle/tests -q
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# The package __init__ imports Home Assistant, which is not installed here. The client itself
# has no HA dependency, so stub the handful of HA modules the package touches at import time.
import types  # noqa: E402

for _name in (
    "homeassistant",
    "homeassistant.config_entries",
    "homeassistant.const",
    "homeassistant.core",
    "homeassistant.helpers",
    "homeassistant.helpers.aiohttp_client",
    "homeassistant.helpers.update_coordinator",
    "homeassistant.exceptions",
):
    sys.modules.setdefault(_name, types.ModuleType(_name))
sys.modules["homeassistant.config_entries"].ConfigEntry = object  # type: ignore[attr-defined]
sys.modules["homeassistant.const"].Platform = types.SimpleNamespace(SENSOR="sensor", BINARY_SENSOR="binary_sensor")  # type: ignore[attr-defined]
sys.modules["homeassistant.core"].HomeAssistant = object  # type: ignore[attr-defined]
sys.modules["homeassistant.helpers.aiohttp_client"].async_get_clientsession = lambda hass: None  # type: ignore[attr-defined]
sys.modules["homeassistant.exceptions"].ConfigEntryAuthFailed = Exception  # type: ignore[attr-defined]


class _DUC:  # minimal DataUpdateCoordinator stand-in so coordinator.py imports
    def __class_getitem__(cls, item):
        return cls


sys.modules["homeassistant.helpers.update_coordinator"].DataUpdateCoordinator = _DUC  # type: ignore[attr-defined]
sys.modules["homeassistant.helpers.update_coordinator"].UpdateFailed = Exception  # type: ignore[attr-defined]

from custom_components.calmneedle.api import (  # noqa: E402
    AuthError,
    CalmNeedleClient,
    DeviceLimitError,
    PairingExpired,
    RateLimitedError,
)


class FakeResp:
    def __init__(self, status: int, body: dict | None = None, headers: dict | None = None) -> None:
        self.status = status
        self._body = body or {}
        self.headers = headers or {}

    async def json(self, content_type=None):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class FakeSession:
    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], list[FakeResp]] = {}
        self.calls: list[tuple[str, str, dict]] = []

    def add(self, method: str, path: str, *resps: FakeResp) -> None:
        self.routes[(method, path)] = list(resps)

    def _take(self, method: str, url: str, headers: dict) -> FakeResp:
        path = url.split("/api/v1", 1)[1]
        self.calls.append((method, path, headers))
        q = self.routes[(method, path)]
        return q.pop(0) if len(q) > 1 else q[0]

    def get(self, url, headers=None, timeout=None):
        return self._take("GET", url, headers or {})

    def post(self, url, json=None, headers=None, timeout=None):
        return self._take("POST", url, headers or {})


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_free_mode_uses_public_endpoints_without_key():
    s = FakeSession()
    s.add("GET", "/score", FakeResp(200, {"overall": 86, "band": "calm"}))
    s.add("GET", "/score/history?hours=48", FakeResp(200, {"points": [{"overall": 86}]}))
    c = CalmNeedleClient(s)
    st = run(c.state("london"))  # scope ignored in free mode
    assert st["overall"] == 86 and st["locked"] and st["history"] == [{"overall": 86}]
    assert all("Authorization" not in h for _, _, h in s.calls)


def test_linked_mode_sends_key_and_install_and_honours_etag():
    s = FakeSession()
    s.add(
        "GET",
        "/integration/state?scope=wales",
        FakeResp(200, {"overall": 80, "categories": {}}, {"ETag": '"abc"'}),
        FakeResp(304),
    )
    c = CalmNeedleClient(s, api_key="cn_live_x_y", install_id="inst-1")
    first = run(c.state("wales"))
    second = run(c.state("wales"))
    assert first == second and first["overall"] == 80
    h1, h2 = s.calls[0][2], s.calls[1][2]
    assert h1["Authorization"] == "Bearer cn_live_x_y" and h1["X-CalmNeedle-Install"] == "inst-1"
    assert "If-None-Match" not in h1 and h2["If-None-Match"] == '"abc"'


def test_typed_errors():
    s = FakeSession()
    s.add("GET", "/integration/state?scope=uk", FakeResp(401, {"error": "invalid_key"}))
    s.add("GET", "/integration/devices", FakeResp(429, {}, {"Retry-After": "600"}))
    c = CalmNeedleClient(s, api_key="k", install_id="i")
    with pytest.raises(AuthError):
        run(c.state("uk"))
    with pytest.raises(RateLimitedError) as ri:
        run(c.devices())
    assert ri.value.retry_after == 600
    s.add(
        "GET",
        "/integration/state?scope=uk",
        FakeResp(403, {"error": "device_limit_reached", "message": "10 devices", "devices": [{}] * 10}),
    )
    with pytest.raises(DeviceLimitError) as di:
        run(c.state("uk"))
    assert len(di.value.devices) == 10


def test_pairing_pending_then_key_then_expired():
    s = FakeSession()
    s.add("POST", "/integration/pair/start", FakeResp(200, {"code": "K7P2QM", "poll_token": "t"}))
    s.add(
        "POST",
        "/integration/pair/poll",
        FakeResp(202, {"status": "pending"}),
        FakeResp(200, {"api_key": "cn_live_a_b"}),
        FakeResp(410, {"error": "expired"}),
    )
    c = CalmNeedleClient(s, install_id="ha")
    start = run(c.pair_start("ha"))
    assert start["code"] == "K7P2QM"
    assert run(c.pair_poll("K7P2QM", "t")) is None
    assert run(c.pair_poll("K7P2QM", "t")) == "cn_live_a_b"
    with pytest.raises(PairingExpired):
        run(c.pair_poll("K7P2QM", "t"))
