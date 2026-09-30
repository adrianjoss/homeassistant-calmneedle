# CalmNeedle for Home Assistant

A live **UK stability score** — 100 is calm, counting down — recalculated every 15 minutes from named UK news outlets and official government data, as Home Assistant entities.

> CalmNeedle is an informational, news-derived indicator. It is not an emergency service, official government advice, or a prediction of specific events. It does not advise any action.

## What you get

| Entity | Free (no account) | Subscriber |
|---|---|---|
| `sensor.calmneedle_uk` — overall score, band, 24 h delta, 48 h history attribute | ✅ | ✅ |
| `sensor.calmneedle_<region>` — home region plus any others you add (14 scopes) | — | ✅ |
| `sensor.calmneedle_security / economy / political / civil_unrest / health / climate` | — | ✅ |
| `sensor.calmneedle_uk` attributes: top-5 active events with justification, next-3 watchlist | — | ✅ |
| `binary_sensor.calmneedle_alert` — on when the score drops ≥ your threshold since reset | — | ✅ |
| `sensor.calmneedle_prepare_tier` — 0/1/2 with the official source link | — | ✅ |

Every entity carries an `attribution` attribute naming CalmNeedle and linking the methodology page. The Civil Unrest sensor carries the same asterisk footnote as the website.

## The device limit, stated up front

A subscription covers **ten devices**; a free account covers **three** (UK sensor only). A Home Assistant instance is *one* device however many phones, tablets or wall panels display it — HA makes one call per cycle on behalf of all of them. A second HA instance, a script, a Grafana panel or a Node-RED flow each use another slot. You can see and revoke devices at https://calmneedle.com/account/api. A key posted publicly fills its ten slots almost immediately and then fails for everyone, including whoever leaked it — that is deliberate.

## Install

**One click:** https://calmneedle.com/homeassistant — the *Install* button opens HACS on your own instance with this repository pre-filled; *Add integration* opens the setup dialog.

**By hand:** HACS → Integrations → ⋮ → Custom repositories → add `https://github.com/adrianjoss/homeassistant-calmneedle` (category *Integration*) → install → restart → Settings → Devices & services → Add integration → CalmNeedle.

## Setup

1. Choose **Continue free** (overall score only, no account) or **Link my account**.
2. Linking shows a six-character code. Open https://calmneedle.com/link while signed in, enter the code, check the region and slot count, approve. The HA screen moves on by itself the moment you approve — the key arrives on its own; you never see or type it.
3. Pick your home region (and any extras) and an alert threshold.

If you see *"This account already has 10 devices linked"*, free a slot on the website and try again. If a key is rotated or revoked, HA asks you to re-link.

## Polling discipline

One request every 15 minutes covers every configured region in a single call (the score cannot change faster), with a per-install 0–60 s jitter so installs don't align on the quarter-hour. Failures that never reached the server (DNS stalls, failed connects) spend none of the budget and retry within 90 seconds; failures that did are retried on a 15 → 30 → 60 minute back-off. Entities keep their last values through short gaps and only go *unavailable* once the data is older than two poll intervals. ETags are honoured. Six requests an hour per device is the server-side ceiling.

## Example automations

Three blueprints ship in `blueprints/automation/calmneedle/` (import in one click from https://calmneedle.com/homeassistant):

- **Band-coloured light** — a lamp follows the band colour (calm green → elevated amber → high orange → severe red, the same tokens as the website).
- **Drop notification** — notify when the score falls by a chosen amount since the last reset.
- **Dashboard card** — a Markdown card with score, band, delta and the top events, ready to paste.

Minimal YAML without a blueprint:

```yaml
automation:
  - alias: CalmNeedle drop
    trigger:
      - platform: state
        entity_id: binary_sensor.calmneedle_alert
        to: "on"
    action:
      - service: notify.mobile_app_my_phone
        data:
          title: "CalmNeedle"
          message: >
            UK score {{ states('sensor.calmneedle_uk') }}
            ({{ state_attr('sensor.calmneedle_uk','band') }}) —
            {{ state_attr('binary_sensor.calmneedle_alert','top_event') }}
      - service: calmneedle.reset_alert
```

## Privacy

The integration sends a random install id it generated itself — no hardware identifiers, no IP allow-listing, nothing about you. Remove and re-add the integration to get a fresh id. CalmNeedle watches the news, not you.

## Reuse of the score

Recognised news organisations may quote or embed the overall score with the attribution "CalmNeedle (calmneedle.com)". Other reuse needs permission: hello@calmneedle.com.

MIT licensed. Run by Adrian at Migrations Limited.
