# Quick start: Python and R clients

This walks through installing either client and pulling data from the live public demo project
**`nyc-manhattan-brooklyn-2026`** (the census tracts of Manhattan and Brooklyn) end to end, in both Python and R. Every command below runs against
the real, production HeatReady API — there's no local mock server or sandbox involved.

## 1. Credential setup

You need a HeatReady username and API key. At a workshop, claim one at
[nishantkishore.com/workshop](https://nishantkishore.com/workshop) with the code from the slide. Otherwise,
contact [datascience_crisisready@harvard.edu](mailto:datascience_crisisready@harvard.edu), or redeem an
invite code if one was issued to you.

**Don't hardcode your key in a script you might commit or share.** Set it as an environment variable
instead:

```bash
export HEATREADY_USERNAME="your-username"
export HEATREADY_KEY="your-key"
```

Both languages below read these two environment variables — swap in a literal string only for a quick
one-off test, never in anything you'll save or share.

## 2. Install

**Python** (requires Python 3.10+):

```bash
pip install "git+https://github.com/crisisready/heat-ready-clients.git#subdirectory=python"
```

**R**:

```r
install.packages("remotes")  # if you don't have it yet
remotes::install_github("crisisready/heat-ready-clients", subdir = "r")
```

## 3. Walkthrough — Python

```python
import os
from heatready import HeatReadyClient

client = HeatReadyClient(
    username=os.environ["HEATREADY_USERNAME"],
    key=os.environ["HEATREADY_KEY"],
)

# A health check needs no credentials at all -- useful to confirm you can reach the API.
print(client.status())
# {'status': 'ok', 'systems': {'database': 'ok', 'era5_pipeline': 'ok'}, 'daily_update_dlq_depth': 0}

# An authenticated health check confirms your username/key actually work.
print(client.ping())
# {'status': 'ok'}

# List every project visible to you (your own, your org's, and public projects).
projects = client.list_projects()
print(len(projects["projects"]), "projects visible")

# Look up the demo project's metadata.
status = client.get_project_status("nyc-manhattan-brooklyn-2026")
print(status["status"], status["polygon_count"], "polygons")
# active 1114 polygons

# Fetch one page of its daily heat-risk metrics (1,114 census tracts x many dates).
page = client.get_metrics("nyc-manhattan-brooklyn-2026", limit=5)
print(page["total_rows"], "total rows available")
for row in page["metrics"]:
    print(row["name"], row["date"], row["day_t2m_max"], row["day_hi_max"])

# Pull every row in a date range (auto-paged).
all_rows = list(client.iter_metrics("nyc-manhattan-brooklyn-2026", date_from="2026-09-01", date_to="2026-09-07"))
print(len(all_rows), "rows downloaded")
```

## 4. Walkthrough — R

```r
library(heatready)

client <- HeatReadyClient$new(
  username = Sys.getenv("HEATREADY_USERNAME"),
  key      = Sys.getenv("HEATREADY_KEY")
)

# A health check needs no credentials at all -- useful to confirm you can reach the API.
client$status()
# $status [1] "ok" ...

# An authenticated health check confirms your username/key actually work.
client$ping()

# List every project visible to you.
projects <- client$list_projects()
nrow(projects$projects)

# Look up the demo project's metadata.
status <- client$get_project_status("nyc-manhattan-brooklyn-2026")
cat(status$status, status$polygon_count, "polygons\n")
# active 1114 polygons

# Fetch one page of its daily heat-risk metrics.
page <- client$get_metrics("nyc-manhattan-brooklyn-2026", limit = 5)
cat(page$total_rows, "total rows available\n")
print(page$metrics[, c("name", "date", "day_t2m_max", "day_hi_max")])

# Pull every row in a date range (auto-paged) as one combined data frame.
all_rows <- client$iter_metrics("nyc-manhattan-brooklyn-2026", date_from = "2026-09-01", date_to = "2026-09-07")
nrow(all_rows)
```

## 5. What you just proved

Both clients: authenticated against production, listed projects, read `nyc-manhattan-brooklyn-2026`'s metadata, fetched
a page of its daily heat-risk metrics, and downloaded a week of metrics for every tract. That is the same shape
of read most integrations need — everything else follows the same pattern of one method call per API
action.

## What these clients can't do

There is no API action to fetch a project's GeoJSON back out once it has been created — GeoJSON is a
write-only input at project-creation time (see `create_project()` in each client's README). If you need a
project's boundary geometry after the fact, that has to come from wherever you originally sourced it, not
from this API.

## Next steps

- The [workshop walkthrough](../walkthrough/) goes further with the same project: one hot day by tract,
  the tracts with the most hot nights, who lives in them, adding your own data, and creating a project.

- Full per-action reference (payload fields, response shapes, rate limits, error codes, the
  root/org_admin/member/read_only access model): the
  [`heat-risk-data-api` API docs](https://github.com/crisisready/heat-risk-data-api/blob/main/docs/api.md).
- Creating your own project from a GeoJSON boundary file: see "Creating a new project" in the
  [Python](../python/README.md#creating-a-new-project) or [R](../r/README.md#creating-a-new-project) README.
- Error handling patterns (the `code` field to branch on, and built-in 503 retry behavior): same two READMEs.
