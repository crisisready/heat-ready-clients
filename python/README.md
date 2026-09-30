# heatready (Python)

Python client for the [HeatReady API](https://github.com/crisisready/heat-risk-data-api).

## Install

```bash
pip install "git+https://github.com/crisisready/heat-ready-clients.git#subdirectory=python"
```

## Quick start

```python
from heatready import HeatReadyClient

client = HeatReadyClient(username="YOUR_USERNAME", key="YOUR_KEY")

client.status()                      # public health check, no credentials needed
client.list_projects()               # every project visible to you
client.get_project_status("nyc-manhattan-brooklyn-2026")
metrics = client.get_metrics("nyc-manhattan-brooklyn-2026", limit=10)   # one page
all_rows = list(client.iter_metrics("nyc-manhattan-brooklyn-2026", date_from="2026-09-01"))  # every row, auto-paged
```

See [`docs/quickstart.md`](../docs/quickstart.md) at the repo root for a full walkthrough against the live
demo project, and [`docs/api.md`](https://github.com/crisisready/heat-risk-data-api/blob/main/docs/api.md)
in `heat-risk-data-api` for the complete per-action reference this client wraps.

## Error handling

Every non-2xx response raises `heatready.HeatReadyError`, with `.code` (a stable, machine-readable
identifier — branch on this, not on `.message`, which may change wording between API versions) and
`.status_code`:

```python
from heatready import HeatReadyError

try:
    client.get_project_status("does-not-exist")
except HeatReadyError as e:
    if e.code == "project_not_found":
        ...
```

A `503 database_unavailable` response is retried automatically (5s, 10s, 20s, 40s backoff, matching the
API's own documented recommendation) before raising.

## Creating a new project

```python
import json

with open("my_area.geojson") as f:
    geojson = json.load(f)

client.create_project("my-new-project", geojson)
# returns immediately with status="initializing" -- poll get_project_status()
# until `start` is set, then call get_metrics()/iter_metrics().
```

There is no API action to fetch a project's GeoJSON back out afterward — it's a write-only input at
creation time, not something this client can download for you.

## Function reference

Every HeatReady API action has a corresponding method, named in `snake_case` (e.g. the `list-projects`
action is `client.list_projects()`). See each method's docstring (`help(HeatReadyClient.get_metrics)`, or
your editor's hover-docs) for its exact parameters, and `client.call(action, payload)` to reach an action
this client doesn't yet have a named method for.

Commonly used, non-root methods:

| Method | What it does |
|---|---|
| `status()` | Public health check |
| `ping()` | Authenticated health check |
| `list_projects()` | List every project visible to you |
| `get_project_status(project_id)` | A project's metadata (bbox, status, polygon count, ...) |
| `create_project(project_id, geojson)` | Create a new project |
| `get_metrics(project_id, ...)` | One page of daily heat-risk metrics |
| `iter_metrics(project_id, ...)` | Every metrics row, auto-paged |
| `get_vulnerability_data(project_id, limit=500, offset=0)` | Per-polygon vulnerability indicators, one page (max 5000 polygons) |
| `get_air_quality_data(project_id, ...)` | Daily air-quality rows |
| `get_lst_data(project_id, ...)` | Land-surface-temperature rows |
| `get_data_availability(project_id)` | Which data layers exist for a project |
| `get_usage()` | Your current-hour rate-limit usage and project counts |
| `rotate_key()` | Issue yourself a new key |

Root-only and admin actions (project lifecycle config, org/user management, downscaling tuning, 100m
onboarding, etc.) are implemented too — see the full method list in
[`src/heatready/client.py`](src/heatready/client.py) or the API reference above.

## Development

```bash
python -m venv .venv && .venv/bin/pip install -e ".[test]"
.venv/bin/pytest tests/ -v
```

Unit tests run entirely against mocked HTTP responses — no credentials or network access needed.
