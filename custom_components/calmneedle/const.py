"""Constants for the CalmNeedle integration (specs/05 section 8)."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "calmneedle"
DEFAULT_BASE_URL = "https://calmneedle.com"
ATTRIBUTION = "CalmNeedle (calmneedle.com) - https://calmneedle.com/methodology"
DISCLAIMER = (
    "CalmNeedle is an informational, news-derived indicator. It is not an emergency service, "
    "official government advice, or a prediction of specific events. It does not advise any action."
)

# 8.7: 15-minute cycle, never faster; backoff 15 -> 30 -> 60 min capped; 0-60 s startup jitter.
SCAN_INTERVAL = timedelta(minutes=15)
BACKOFF_STEPS = (15, 30, 60)
STARTUP_JITTER_MAX_S = 60

CONF_API_KEY = "api_key"
CONF_INSTALL_ID = "install_id"
CONF_HOME_REGION = "home_region"
CONF_EXTRA_REGIONS = "extra_regions"
CONF_DROP_THRESHOLD = "drop_threshold"
CONF_MODE = "mode"
MODE_FREE = "free"
MODE_LINKED = "linked"
DEFAULT_DROP_THRESHOLD = 5

INSTALL_HEADER = "X-CalmNeedle-Install"

SCOPES = {
    "uk": "United Kingdom",
    "england": "England",
    "scotland": "Scotland",
    "wales": "Wales",
    "northern-ireland": "Northern Ireland",
    "north-east": "North East",
    "north-west": "North West",
    "yorkshire": "Yorkshire & the Humber",
    "east-midlands": "East Midlands",
    "west-midlands": "West Midlands",
    "east-of-england": "East of England",
    "london": "London",
    "south-east": "South East",
    "south-west": "South West",
}
CATEGORIES = ("security", "economy", "political", "civil_unrest", "health", "climate")
CIVIL_UNREST_FOOTNOTE = (
    "* Includes signals from public trending topics (capped) alongside reported events; "
    "see the methodology page."
)

# Band colours from the design tokens (web/src/tokens.css) - used by the band-coloured light blueprint.
BAND_COLOURS = {
    "calm": "#4FB286",
    "elevated": "#D9A63C",
    "high": "#DE7C4B",
    "severe": "#D8504A",
}
