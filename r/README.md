# heatready (R)

R client for the [HeatReady API](https://github.com/crisisready/heat-risk-data-api).

## Install

```r
# install.packages("remotes")  # if you don't have it yet
remotes::install_github("crisisready/heat-ready-clients", subdir = "r")
```

## Quick start

```r
library(heatready)

client <- HeatReadyClient$new(username = "YOUR_USERNAME", key = "YOUR_KEY")

client$status()                                 # public health check, no credentials needed
client$list_projects()                          # every project visible to you
client$get_project_status("nyc-manhattan-brooklyn-2026")
metrics <- client$get_metrics("nyc-manhattan-brooklyn-2026", limit = 10)   # one page
all_rows <- client$iter_metrics("nyc-manhattan-brooklyn-2026", date_from = "2026-09-01")  # every row, auto-paged, as a data frame
```

See [`docs/quickstart.md`](../docs/quickstart.md) at the repo root for a full walkthrough against the live
demo project, and [`docs/api.md`](https://github.com/crisisready/heat-risk-data-api/blob/main/docs/api.md)
in `heat-risk-data-api` for the complete per-action reference this client wraps.

## Error handling

Every non-2xx response signals a condition of class `heatready_error`, with `$code` (a stable,
machine-readable identifier — branch on this, not on the message text, which may change wording between API
versions) and `$status_code`:

```r
result <- tryCatch(
  client$get_project_status("does-not-exist"),
  heatready_error = function(e) {
    if (identical(e$code, "project_not_found")) {
      message("no such project")
    } else {
      stop(e)
    }
  }
)
```

A `503` (database momentarily unavailable) response is retried automatically (5s, 10s, 20s, 40s backoff,
matching the API's own documented recommendation) before raising.

## Creating a new project

```r
# simplifyVector = FALSE preserves GeoJSON array nesting faithfully on re-serialization
geojson <- jsonlite::fromJSON("my_area.geojson", simplifyVector = FALSE)
client$create_project("my-new-project", geojson)
# returns immediately with status = "initializing" -- poll get_project_status()
# until `start` is set, then call get_metrics()/iter_metrics().
```

There is no API action to fetch a project's GeoJSON back out afterward — it's a write-only input at
creation time, not something this client can download for you.

## Function reference

Every HeatReady API action has a corresponding method, named in `snake_case` (e.g. the `list-projects`
action is `client$list_projects()`). Run `?HeatReadyClient` for the full method list with parameters, or
`client$call(action, payload)` to reach an action this client doesn't yet have a named method for.

Commonly used, non-root methods: `status()`, `ping()`, `list_projects()`, `get_project_status()`,
`create_project()`, `get_metrics()`, `iter_metrics()`, `get_vulnerability_data()`,
`get_air_quality_data()`, `get_lst_data()`, `get_data_availability()`, `get_usage()`, `rotate_key()`.

Root-only and admin actions (project lifecycle config, org/user management, downscaling tuning, 100m
onboarding, etc.) are implemented too — see [`R/client.R`](R/client.R) or the API reference above.

## Development

```r
roxygen2::roxygenise(".")   # regenerate NAMESPACE/man/ after editing R/client.R
devtools::test(".")         # or: testthat::test_dir("tests/testthat")
```

Unit tests run entirely against `httr2::local_mocked_responses()` — no credentials or network access
needed.
