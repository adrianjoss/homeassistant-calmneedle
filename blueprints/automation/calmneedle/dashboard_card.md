# CalmNeedle dashboard card

Paste this as a **Markdown card** (Edit dashboard → Add card → Markdown → Show code editor).
Works with the free `sensor.calmneedle_uk`; the events section appears for subscribers.

```yaml
type: markdown
title: CalmNeedle
content: >
  {% set s = 'sensor.calmneedle_uk' %}
  {% set band = state_attr(s, 'band') or 'calm' %}
  {% set colour = {'calm': '#4FB286', 'elevated': '#D9A63C', 'high': '#DE7C4B', 'severe': '#D8504A'}[band] %}
  ## <font color="{{ colour }}">{{ states(s) }}</font> <small>{{ band | title }}
  {% set d = state_attr(s, 'delta_24h') %}
  {% if d is number %}· {{ '%+d' % d }} in 24 h{% endif %}</small>

  {% set events = state_attr(s, 'events') or [] %}
  {% if events %}
  **What is moving it**
  {% for e in events[:3] %}
  - **{{ e.title }}** <small>({{ e.category | replace('_',' ') }}{% if e.category == 'civil_unrest' %}*{% endif %})</small> — {{ e.justification }}
  {% endfor %}
  {% endif %}

  {% set w = state_attr(s, 'watchlist') or [] %}
  {% if w %}
  **Coming up** — {% for i in w %}{{ i.date }}: {{ i.title }}{% if not loop.last %} · {% endif %}{% endfor %}
  {% endif %}

  <small>Updated {{ state_attr(s, 'updated_at') | as_timestamp | timestamp_custom('%H:%M') }} ·
  [CalmNeedle](https://calmneedle.com) · not official, not a forecast</small>
```

A **gauge card** for the needle look:

```yaml
type: gauge
entity: sensor.calmneedle_uk
name: UK stability
min: 0
max: 100
needle: true
severity:
  green: 85
  yellow: 70
  red: 0
```
