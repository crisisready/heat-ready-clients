#' @importFrom R6 R6Class
#' @importFrom httr2 request req_body_json req_timeout req_error req_perform
#' @importFrom httr2 resp_status resp_body_json resp_body_string
NULL

#' Default HeatReady API base URL
#' @keywords internal
DEFAULT_BASE_URL <- "https://5trhrgas69.execute-api.us-east-1.amazonaws.com/v1"

#' Seconds to wait between retries of a 503 (database momentarily
#' unavailable) response -- the API's own docs recommend this exact
#' schedule.
#' @keywords internal
DEFAULT_RETRY_DELAYS <- c(5, 10, 20, 40)

#' Signal a HeatReady API error
#'
#' @param message Human-readable error text from the API's `error` field.
#' @param code Stable, machine-readable identifier from the API's `code`
#'   field (e.g. `"project_not_found"`). Branch on this, not on `message`
#'   text, which may change wording between API versions. May be `NULL` for
#'   a response the API didn't tag with a code.
#' @param status_code The HTTP status code returned.
#' @keywords internal
heatready_error <- function(message, code, status_code) {
  structure(
    class = c("heatready_error", "rlang_error", "error", "condition"),
    list(
      message = sprintf("%s (code=%s, http=%s)", message, code %||% "NA", status_code),
      call = sys.call(-1),
      code = code,
      status_code = status_code
    )
  )
}

`%||%` <- function(a, b) if (is.null(a)) b else a

#' Drop NULL entries from a named list
#' @keywords internal
compact <- function(x) x[!vapply(x, is.null, logical(1))]

#' Flatten a nested data.frame column into a plain list column
#'
#' `jsonlite`'s `simplifyVector` turns a JSON array of nested objects (e.g. a
#' metrics row's nullable `downscaled` object, which itself nests `tmax`/
#' `tmin`/`station`/`metrics` objects) into a data.frame-within-a-data.frame.
#' That's fine for a single page, but `rbind()`-ing two such pages together
#' reliably fails (`"number of items to replace is not a multiple of
#' replacement length"`) once the nested frames' per-row NA patterns differ
#' between pages. Converting to a plain list column (one named list per row,
#' recursively) sidesteps the problem entirely and is arguably a more natural
#' R representation of "a nullable nested object" anyway.
#' @keywords internal
flatten_nested_column <- function(col) {
  # Flatten each sub-column exactly once (not once per row) -- recursing
  # inside the per-row lapply below would make this quadratic (or worse, for
  # multiply-nested columns) in the number of rows.
  flat_subcols <- lapply(col, function(subcol) {
    if (is.data.frame(subcol)) flatten_nested_column(subcol) else subcol
  })
  lapply(seq_len(nrow(col)), function(i) {
    row <- lapply(flat_subcols, `[[`, i)
    stats::setNames(row, names(col))
  })
}

#' Replace any nested-data.frame columns in a metrics page with plain list
#' columns, so pages can be safely `rbind()`-ed together.
#' @keywords internal
normalize_metrics_page <- function(df) {
  if (!is.data.frame(df) || nrow(df) == 0) return(df)
  nested_cols <- names(df)[vapply(df, is.data.frame, logical(1))]
  for (col in nested_cols) df[[col]] <- I(flatten_nested_column(df[[col]]))
  df
}

#' HeatReadyClient
#'
#' A thin, authenticated wrapper around the HeatReady `/evaluate` API. The
#' HeatReady API is a single-endpoint action router: every request is a
#' `POST` to `/evaluate` with a JSON body of `{username, key, action,
#' payload}`, and the `action` field selects the operation. This client
#' wraps that envelope so callers write `client$list_projects()` instead of
#' building the request body by hand.
#'
#' See the full API reference at
#' <https://nishantkishore.com/workshop/api>
#' for per-action payload fields, response shapes, and the access-control
#' model (root / org_admin / member / read_only / public-project).
#'
#' @examples
#' \dontrun{
#' client <- HeatReadyClient$new(username = "alice", key = "...")
#' client$list_projects()
#' }
#'
#' @export
HeatReadyClient <- R6::R6Class("HeatReadyClient",
  public = list(
    #' @field username Your HeatReady account username.
    username = NULL,
    #' @field key Your HeatReady API key.
    key = NULL,
    #' @field base_url API base URL.
    base_url = NULL,
    #' @field timeout_s Per-request timeout in seconds.
    timeout_s = NULL,
    #' @field retry_delays Seconds to wait between retries of a 503 response.
    retry_delays = NULL,

    #' @description Create a new client.
    #' @param username Your HeatReady account username. Pass `""` only for
    #'   the unauthenticated `status` action.
    #' @param key Your HeatReady API key.
    #' @param base_url API base URL. Defaults to the production endpoint;
    #'   override for a dev/staging stack.
    #' @param timeout_s Per-request timeout in seconds.
    #' @param retry_delays Seconds to wait between retries of a `503`
    #'   (database momentarily unavailable) response, one attempt per entry.
    #'   Pass `numeric(0)` to disable retries.
    initialize = function(username, key, base_url = DEFAULT_BASE_URL,
                           timeout_s = 30, retry_delays = DEFAULT_RETRY_DELAYS) {
      self$username <- username
      self$key <- key
      self$base_url <- sub("/+$", "", base_url)
      self$timeout_s <- timeout_s
      self$retry_delays <- retry_delays
    },

    #' @description Low-level call: POSTs one `{action, payload}` request.
    #'   Every named method on this client is a thin wrapper over this call.
    #'   Use it directly for an action this client doesn't yet have a named
    #'   method for.
    #' @param action The API action name, e.g. `"list-projects"`.
    #' @param payload A named list of action-specific arguments, or `NULL`
    #'   for actions that take none.
    #' @return The parsed JSON response body, as a list (nested data frames
    #'   for arrays of homogeneous row objects, via `httr2`'s
    #'   `simplifyVector`).
    call = function(action, payload = NULL) {
      body <- list(username = self$username, key = self$key, action = action)
      if (!is.null(payload)) body$payload <- payload

      attempt <- 0
      repeat {
        if (attempt > 0) Sys.sleep(self$retry_delays[attempt])
        req <- httr2::request(paste0(self$base_url, "/evaluate"))
        req <- httr2::req_body_json(req, body, auto_unbox = TRUE)
        req <- httr2::req_timeout(req, self$timeout_s)
        req <- httr2::req_error(req, is_error = function(resp) FALSE)
        resp <- httr2::req_perform(req)
        status <- httr2::resp_status(resp)
        if (status != 503 || attempt >= length(self$retry_delays)) break
        attempt <- attempt + 1
      }

      data <- tryCatch(
        httr2::resp_body_json(resp, simplifyVector = TRUE),
        error = function(e) list()
      )
      if (status < 200 || status >= 300) {
        stop(heatready_error(
          message = data$error %||% httr2::resp_body_string(resp),
          code = data$code,
          status_code = status
        ))
      }
      data
    },

    # -- health -----------------------------------------------------------

    #' @description Public, unauthenticated health check. No credentials required.
    status = function() self$call("status"),

    #' @description Authenticated health check -- confirms your username/key work.
    ping = function() self$call("ping"),

    # -- credentials --------------------------------------------------------

    #' @description Create a new user. Root only. Returns the plaintext key -- shown once.
    #' @param username New account's username.
    #' @param org_id Optional org to assign (defaults server-side if omitted).
    #' @param role Optional org role (`"org_admin"` | `"member"` | `"read_only"`).
    create_user = function(username, org_id = NULL, role = NULL) {
      self$call("create-user", compact(list(username = username, org_id = org_id, role = role)))
    },

    #' @description Create a new root user. Root only. Returns the plaintext key -- shown once.
    #' @param username New root account's username.
    create_root_user = function(username) {
      self$call("create-root-user", list(username = username))
    },

    #' @description Create a single-use invite code for self-service signup. Root or org_admin.
    #' @param label Free-text note (not shown to the redeemer).
    #' @param org_id Org the invite grants membership in.
    #' @param role Role granted on redemption (default `"member"`).
    create_invite = function(label, org_id, role = "member") {
      self$call("create-invite", list(label = label, org_id = org_id, role = role))
    },

    #' @description Revoke an unredeemed invite code. Root only.
    #' @param code The invite code.
    revoke_invite = function(code) self$call("revoke-invite", list(code = code)),

    #' @description Self-serve signup with an invite code. Unauthenticated -- no key needed yet.
    #' @param code The invite code.
    #' @param username Desired username.
    redeem_invite = function(code, username) {
      self$call("redeem-invite", list(code = code, username = username))
    },

    #' @description Delete a user account. Root only.
    #' @param username Account to delete.
    delete_user = function(username) self$call("delete-user", list(username = username)),

    #' @description Issue yourself a new key; the old one stops working
    #'   immediately (no grace window).
    rotate_key = function() self$call("rotate-key"),

    #' @description Current-hour `evaluate-heat-risk` usage and project
    #'   counts for yourself (or, for a root/org_admin caller, another user).
    #' @param username Optional -- another user to check (root/org_admin only).
    get_usage = function(username = NULL) {
      self$call("get-usage", compact(list(username = username)))
    },

    # -- organizations & users (root / org_admin) ----------------------------

    #' @description Create an organization. Root only.
    #' @param org_id New org's identifier.
    #' @param name New org's display name.
    create_org = function(org_id, name) self$call("create-org", list(org_id = org_id, name = name)),

    #' @description List every organization on the platform. Root only.
    list_orgs = function() self$call("list-orgs"),

    #' @description List users, optionally scoped to one org. Root or
    #'   org_admin (org_admin is hard-scoped to its own org).
    #' @param org_id Optional org to scope to.
    list_users = function(org_id = NULL) self$call("list-users", compact(list(org_id = org_id))),

    #' @description Set a user's org role. Root or org_admin (own org, may
    #'   not grant org_admin or touch root).
    #' @param username Target account.
    #' @param role New role (`"org_admin"` | `"member"` | `"read_only"`).
    set_user_role = function(username, role) self$call("set-user-role", list(username = username, role = role)),

    #' @description Move a user to a different org (re-tenants their owned
    #'   projects too). Root only.
    #' @param username Target account.
    #' @param org_id Destination org.
    set_user_org = function(username, org_id) self$call("set-user-org", list(username = username, org_id = org_id)),

    # -- projects: lifecycle --------------------------------------------------

    #' @description Create a new project from a GeoJSON FeatureCollection.
    #'   Returns immediately with `status = "initializing"` -- poll
    #'   `get_project_status()` until `start` is set, then call
    #'   `get_metrics()`. For faithful coordinate serialization, load your
    #'   GeoJSON with `jsonlite::fromJSON(path, simplifyVector = FALSE)`
    #'   rather than the default simplifying reader.
    #' @param project_id Unique project identifier.
    #' @param geojson A parsed GeoJSON FeatureCollection (list).
    create_project = function(project_id, geojson) {
      self$call("evaluate-heat-risk", list(project_id = project_id, json_obj = geojson))
    },

    #' @description Create a project (pass `geojson`) or fetch one page of
    #'   an existing project's daily heat-risk metrics. See `create_project`
    #'   and `get_metrics` for the two common cases as separate calls.
    #' @param project_id Project identifier.
    #' @param geojson GeoJSON FeatureCollection (new projects only).
    #' @param limit Max rows per page (default 500, max 2000).
    #' @param offset Row offset for pagination.
    #' @param date_from Filter -- only rows on/after this local date (`YYYY-MM-DD`).
    #' @param date_to Filter -- only rows on/before this local date (`YYYY-MM-DD`).
    #' @param include_forecast Include forecast rows in the response (default `FALSE`).
    evaluate_heat_risk = function(project_id, geojson = NULL, limit = NULL, offset = NULL,
                                   date_from = NULL, date_to = NULL, include_forecast = NULL) {
      payload <- compact(list(
        project_id = project_id, json_obj = geojson, limit = limit, offset = offset,
        date_from = date_from, date_to = date_to, include_forecast = include_forecast
      ))
      self$call("evaluate-heat-risk", payload)
    },

    #' @description Fetch one page (default up to 500 rows) of an existing,
    #'   ready project's daily heat-risk metrics. See `iter_metrics` to walk
    #'   every page automatically.
    #' @param project_id Project identifier.
    #' @param limit Max rows per page (default 500, max 2000).
    #' @param offset Row offset for pagination.
    #' @param date_from Filter -- only rows on/after this local date.
    #' @param date_to Filter -- only rows on/before this local date.
    #' @param include_forecast Include forecast rows (default `FALSE`).
    get_metrics = function(project_id, limit = 500, offset = 0, date_from = NULL,
                            date_to = NULL, include_forecast = FALSE) {
      self$evaluate_heat_risk(project_id, limit = limit, offset = offset,
                               date_from = date_from, date_to = date_to,
                               include_forecast = include_forecast)
    },

    #' @description Fetch every metrics row for a project, paging
    #'   automatically, and return them as one combined data frame.
    #'
    #'   This is the "download all of a project's data" helper: it walks
    #'   `limit`/`offset` for you.
    #' @param project_id Project identifier.
    #' @param page_size Rows requested per page (default 500).
    #' @param date_from Filter -- only rows on/after this local date.
    #' @param date_to Filter -- only rows on/before this local date.
    #' @param include_forecast Include forecast rows (default `FALSE`).
    #' @return A data frame with one row per polygon per local date.
    iter_metrics = function(project_id, page_size = 500, date_from = NULL,
                             date_to = NULL, include_forecast = FALSE) {
      offset <- 0
      pages <- list()
      repeat {
        page <- self$get_metrics(project_id, limit = page_size, offset = offset,
                                  date_from = date_from, date_to = date_to,
                                  include_forecast = include_forecast)
        if (is.null(page$metrics)) {
          stop(heatready_error(
            message = sprintf(
              "Project '%s' has no metrics yet -- it's still initializing (%s). Poll get_project_status() until 'start' is set before calling iter_metrics().",
              project_id, page$message %||% page$status %||% "no metrics in response"
            ),
            code = "project_not_ready",
            status_code = 202
          ))
        }
        rows <- page$metrics
        n <- if (is.data.frame(rows)) nrow(rows) else length(rows)
        if (is.null(n) || n == 0) break
        pages[[length(pages) + 1]] <- normalize_metrics_page(rows)
        offset <- offset + n
        if (offset >= page$total_rows) break
      }
      if (length(pages) == 0) return(data.frame())
      do.call(rbind, pages)
    },

    #' @description Permanently delete a project and its data. Owner or
    #'   root. Cannot be undone.
    #' @param project_id Project identifier.
    delete_project = function(project_id) self$call("delete-project", list(project_id = project_id)),

    #' @description Get a project's metadata (bbox, status, polygon count,
    #'   WMO reference progress, etc.).
    #' @param project_id Project identifier.
    get_project_status = function(project_id) self$call("get-project-status", list(project_id = project_id)),

    #' @description List every project visible to you (your own, your
    #'   org's, and public projects).
    list_projects = function() self$call("list-projects"),

    #' @description Mark a project inactive (stops its daily updates). Owner or root.
    #' @param project_id Project identifier.
    set_project_inactive = function(project_id) self$call("set-project-inactive", list(project_id = project_id)),

    #' @description Mark a project active again. Owner or root.
    #' @param project_id Project identifier.
    set_project_active = function(project_id) self$call("set-project-active", list(project_id = project_id)),

    #' @description Make a project readable cross-org (or revoke that). Root only.
    #' @param project_id Project identifier.
    #' @param public `TRUE`/`FALSE`.
    set_project_public = function(project_id, public) {
      self$call("set-project-public", list(project_id = project_id, public = public))
    },

    #' @description Transfer project ownership to another user (cross-org requires root).
    #' @param project_id Project identifier.
    #' @param new_owner Destination username.
    transfer_project = function(project_id, new_owner) {
      self$call("transfer-project", list(project_id = project_id, new_owner = new_owner))
    },

    #' @description Extend a project's history backwards before its current start date.
    #' @param project_id Project identifier.
    #' @param days Days of history to add.
    backfill_project = function(project_id, days) {
      self$call("backfill-project", list(project_id = project_id, days = days))
    },

    # -- downscaling & dataset config (root only) ------------------------------

    #' @description Per-project opt-in for neighborhood-resolution downscaling. Root only.
    #' @param project_id Project identifier.
    #' @param enabled `TRUE`/`FALSE`.
    set_project_downscaling = function(project_id, enabled) {
      self$call("set-project-downscaling", list(project_id = project_id, enabled = enabled))
    },

    #' @description Per-project opt-out for the Tier-2 nearby-station blend refinement. Root only.
    #' @param project_id Project identifier.
    #' @param enabled `TRUE`/`FALSE`.
    set_project_station_blend = function(project_id, enabled) {
      self$call("set-project-station-blend", list(project_id = project_id, enabled = enabled))
    },

    #' @description Switch a project's ERA5 dataset. Root only; affects future fetches only.
    #' @param project_id Project identifier.
    #' @param dataset `"reanalysis-era5-land"` or `"reanalysis-era5-single-levels"`.
    set_project_dataset = function(project_id, dataset) {
      self$call("set-project-dataset", list(project_id = project_id, dataset = dataset))
    },

    #' @description Force-overwrite a project's stored ERA5 history at its current dataset. Root only.
    #' @param project_id Project identifier.
    rebackfill_era5_history = function(project_id) {
      self$call("rebackfill-era5-history", list(project_id = project_id))
    },

    #' @description Enqueue an on-demand daily_update run for one project. Root only.
    #' @param project_id Project identifier.
    trigger_daily_update = function(project_id) {
      self$call("trigger-daily-update", list(project_id = project_id))
    },

    #' @description Write real Tier-1/Tier-2 downscaled rows for an explicit date range. Root only.
    #' @param project_id Project identifier.
    #' @param date_from Start date (`YYYY-MM-DD`).
    #' @param date_to End date (`YYYY-MM-DD`).
    backfill_downscaling = function(project_id, date_from, date_to) {
      self$call("backfill-downscaling", list(project_id = project_id, date_from = date_from, date_to = date_to))
    },

    #' @description Read-only: count downscaled rows that don't match their base metrics row. Root only.
    #' @param project_id Project identifier.
    #' @param date_from Optional start date filter.
    #' @param date_to Optional end date filter.
    check_served_integrity = function(project_id, date_from = NULL, date_to = NULL) {
      self$call("check-served-integrity", compact(list(project_id = project_id, date_from = date_from, date_to = date_to)))
    },

    #' @description Repair grid_* served columns from their base row where they already match. Root only.
    #' @param project_id Project identifier.
    #' @param date_from Optional start date filter.
    #' @param date_to Optional end date filter.
    repair_grid_base = function(project_id, date_from = NULL, date_to = NULL) {
      self$call("repair-grid-base", compact(list(project_id = project_id, date_from = date_from, date_to = date_to)))
    },

    #' @description Start computing a project's WMO reference climatology. Owner or root.
    #' @param project_id Project identifier.
    #' @param force Recompute even if already in progress (default `FALSE`).
    compute_wmo_reference = function(project_id, force = FALSE) {
      payload <- list(project_id = project_id)
      if (isTRUE(force)) payload$force <- force
      self$call("compute-wmo-reference", payload)
    },

    #' @description Not implemented server-side yet -- returns a stub response.
    compute_wmo_utci_reference = function() self$call("compute-wmo-utci-reference"),

    #' @description Backfill UTCI/WBGT thermal-comfort columns for a project. Owner or root.
    #' @param project_id Project identifier.
    backfill_utci = function(project_id) self$call("backfill-utci", list(project_id = project_id)),

    #' @description Export the global ghcn_training table to gzip JSONL on S3 (paged, async). Root only.
    export_ghcn_training = function() self$call("export-ghcn-training", list()),

    # -- vulnerability, air quality, LST, nighttime persistence ---------------

    #' @description Extract vulnerability indicators (RWI, VIIRS, health facilities, etc.) for a project.
    #' @param project_id Project identifier.
    backfill_vulnerability = function(project_id) self$call("backfill-vulnerability", list(project_id = project_id)),

    #' @description Fetch a project's per-polygon vulnerability indicators, one
    #'   page of up to `limit` polygons. Page with `offset` when a project has
    #'   more polygons than one page holds.
    #' @param project_id Project identifier.
    #' @param limit Max polygons per page (default 500, max 5000).
    #' @param offset Polygons to skip, for paging past `limit`.
    get_vulnerability_data = function(project_id, limit = 500, offset = 0) {
      self$call("get-vulnerability-data", list(project_id = project_id, limit = limit, offset = offset))
    },

    #' @description Recompute population/timezone/area columns from the project's current GeoJSON.
    #' @param project_id Project identifier.
    resync_population = function(project_id) self$call("resync-population", list(project_id = project_id)),

    #' @description Backfill CAMS/OpenAQ air-quality history for a project.
    #' @param project_id Project identifier.
    #' @param days Optional days of history to fetch.
    backfill_air_quality = function(project_id, days = NULL) {
      self$call("backfill-air-quality", compact(list(project_id = project_id, days = days)))
    },

    #' @description Fetch daily air-quality rows (PM2.5/PM10/NO2/O3/SO2/CO + AQI) for a project.
    #' @param project_id Project identifier.
    #' @param date_from Optional start date filter.
    #' @param date_to Optional end date filter.
    #' @param limit Max rows (default 500, max 5000).
    #' @param offset Row offset for pagination.
    #' @param include_flagged Include `qc_status = "invalid"` rows (default `FALSE`).
    get_air_quality_data = function(project_id, date_from = NULL, date_to = NULL,
                                     limit = 500, offset = 0, include_flagged = FALSE) {
      payload <- compact(list(
        project_id = project_id, date_from = date_from, date_to = date_to,
        limit = limit, offset = offset, include_flagged = include_flagged
      ))
      self$call("get-air-quality-data", payload)
    },

    #' @description Delete one (name, date) air-quality row. Root only;
    #'   prefer QC-flagging over deleting.
    #' @param project_id Project identifier.
    #' @param name Polygon name.
    #' @param date Row date (`YYYY-MM-DD`).
    delete_air_quality_row = function(project_id, name, date) {
      self$call("delete-air-quality-row", list(project_id = project_id, name = name, date = date))
    },

    #' @description Backfill Landsat land-surface-temperature history. Pass
    #'   `days` OR `composite_prep` (mutually exclusive), not both.
    #' @param project_id Project identifier.
    #' @param days Days of history to search (default 365 server-side).
    #' @param composite_prep Backfill the three most recent warm-season windows instead.
    backfill_lst = function(project_id, days = NULL, composite_prep = NULL) {
      self$call("backfill-lst", compact(list(project_id = project_id, days = days, composite_prep = composite_prep)))
    },

    #' @description Fetch Landsat land-surface-temperature rows for a
    #'   project (one row per polygon per clear satellite overpass -- not a
    #'   daily series).
    #' @param project_id Project identifier.
    #' @param date_from Optional start date filter.
    #' @param date_to Optional end date filter.
    #' @param latest_only Return only the single freshest row per polygon (default `FALSE`).
    #' @param limit Max rows when `latest_only` is `FALSE` (default 500, max 5000).
    #' @param offset Row offset when `latest_only` is `FALSE`.
    get_lst_data = function(project_id, date_from = NULL, date_to = NULL,
                             latest_only = FALSE, limit = 500, offset = 0) {
      payload <- list(project_id = project_id, latest_only = latest_only)
      if (!isTRUE(latest_only)) {
        payload$limit <- limit
        payload$offset <- offset
      }
      payload <- c(payload, compact(list(date_from = date_from, date_to = date_to)))
      self$call("get-lst-data", payload)
    },

    #' @description Per-tract nighttime-heat streak/density/season-count, each with a coverage flag.
    #' @param project_id Project identifier.
    get_nighttime_persistence = function(project_id) {
      self$call("get-nighttime-persistence", list(project_id = project_id))
    },

    #' @description Top-quartile nighttime persistence x elderly-75+/young-under-5 shortlists.
    #' @param project_id Project identifier.
    get_nighttime_vulnerability_overlay = function(project_id) {
      self$call("get-nighttime-vulnerability-overlay", list(project_id = project_id))
    },

    # -- data availability, provisioning, layers -------------------------------

    #' @description Per-project rollup of which data layers exist, computed live on every call.
    #' @param project_id Project identifier.
    get_data_availability = function(project_id) self$call("get-data-availability", list(project_id = project_id)),

    #' @description Public-content feed of downscaling model gates and fleet
    #'   tier mix across every public project. Not project-scoped.
    #' @param window_days Rolling window in days (default 7).
    downscaling_fleet_status = function(window_days = 7) {
      self$call("downscaling-fleet-status", list(window_days = window_days))
    },

    #' @description Self-serve request to enable one data layer (e.g. `"age_structure"`) for a project.
    #' @param project_id Project identifier.
    #' @param layer Layer name.
    enable_data_layer = function(project_id, layer) {
      self$call("enable-data-layer", list(project_id = project_id, layer = layer))
    },

    #' @description System-wide snapshot of the provisioning queue and 100m WorldPop mirror. Root only.
    get_provisioning_status = function() self$call("get-provisioning-status"),

    #' @description List the WorldPop 100m-onboarding registry. Root only.
    list_100m_countries = function() self$call("list-100m-countries"),

    #' @description Mark a country ready for 100m age-structure data. Root only.
    #' @param iso3 ISO3 country code.
    complete_100m_onboarding = function(iso3) self$call("complete-100m-onboarding", list(iso3 = iso3)),

    #' @description Re-queue a failed/wedged country's 100m onboarding. Root only.
    #' @param iso3 ISO3 country code.
    reset_100m_onboarding = function(iso3) self$call("reset-100m-onboarding", list(iso3 = iso3)),

    # -- LLM interpretation (experimental) -------------------------------------

    #' @description Submit an async LLM interpretation request for a date
    #'   range. Experimental; rate-limited to 5 requests/user/24h. Poll
    #'   `get_interpretation_result()`.
    #' @param project_id Project identifier.
    #' @param start_date Start date (`YYYY-MM-DD`).
    #' @param end_date End date (`YYYY-MM-DD`).
    get_heat_risk_interpretation = function(project_id, start_date, end_date) {
      self$call("get-heat-risk-interpretation",
                list(project_id = project_id, start_date = start_date, end_date = end_date))
    },

    #' @description Poll the result of a `get_heat_risk_interpretation()` request. Experimental.
    #' @param llm_req_key Request key returned by `get_heat_risk_interpretation()`.
    get_interpretation_result = function(llm_req_key) {
      self$call("get-interpretation-result", list(llm_req_key = llm_req_key))
    }
  )
)
