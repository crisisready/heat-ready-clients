"""Python client for the HeatReady API.

The HeatReady API is a single-endpoint action router: every request is a
``POST`` to ``/evaluate`` with a JSON body of ``{username, key, action,
payload}``, and the ``action`` field selects the operation. This client wraps
that envelope so callers write ``client.list_projects()`` instead of building
the request body by hand.

See the full API reference at
https://github.com/crisisready/heat-risk-data-api/blob/main/docs/api.md for
per-action payload fields, response shapes, and the access-control model
(root / org_admin / member / read_only / public-project).
"""

from __future__ import annotations

import time
from typing import Any, Iterator

import requests

from .exceptions import HeatReadyError

DEFAULT_BASE_URL = "https://5trhrgas69.execute-api.us-east-1.amazonaws.com/v1"

# HTTP 503 means Aurora is momentarily unreachable, not a bad request -- the
# API's own docs recommend retrying with this exact backoff schedule.
DEFAULT_RETRY_DELAYS = (5, 10, 20, 40)


class HeatReadyClient:
    """A thin, authenticated wrapper around the HeatReady ``/evaluate`` API.

    Example:
        >>> client = HeatReadyClient(username="alice", key="...")
        >>> client.list_projects()
        {'projects': [...]}

    Args:
        username: Your HeatReady account username. Pass ``""`` (or omit
            username/key together) only for the unauthenticated ``status``
            action.
        key: Your HeatReady API key.
        base_url: API base URL. Defaults to the production endpoint; override
            for a dev/staging stack.
        timeout: Per-request timeout in seconds.
        retry_delays: Seconds to wait between retries of a ``503`` (database
            momentarily unavailable) response, one attempt per entry. Pass
            ``()`` to disable retries.
        session: An optional pre-configured ``requests.Session`` (e.g. to
            reuse connections, set default headers, or plug in a test
            transport adapter). A new session is created if omitted.
    """

    def __init__(
        self,
        username: str,
        key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
        retry_delays: tuple[float, ...] = DEFAULT_RETRY_DELAYS,
        session: requests.Session | None = None,
    ) -> None:
        self.username = username
        self.key = key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retry_delays = retry_delays
        self._session = session or requests.Session()

    # -- transport -----------------------------------------------------

    def _call(self, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Low-level call: POSTs one ``{action, payload}`` request.

        Every named method on this class is a thin wrapper over this call.
        Use it directly for an action this client doesn't yet have a named
        method for.

        Raises:
            HeatReadyError: on any non-2xx response (after retries for 503).
        """
        body: dict[str, Any] = {"username": self.username, "key": self.key, "action": action}
        if payload is not None:
            body["payload"] = payload

        url = f"{self.base_url}/evaluate"
        attempts = (0,) + tuple(range(1, len(self.retry_delays) + 1))
        response = None
        for attempt in attempts:
            if attempt > 0:
                time.sleep(self.retry_delays[attempt - 1])
            response = self._session.post(url, json=body, timeout=self.timeout)
            if response.status_code != 503:
                break

        assert response is not None  # attempts always has at least one entry
        data: dict[str, Any] = response.json() if response.content else {}
        if not response.ok:
            raise HeatReadyError(
                message=data.get("error", response.text),
                code=data.get("code"),
                status_code=response.status_code,
            )
        return data

    # -- health ----------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Public, unauthenticated health check. No credentials required."""
        return self._call("status")

    def ping(self) -> dict[str, Any]:
        """Authenticated health check -- confirms your username/key work."""
        return self._call("ping")

    # -- credentials -------------------------------------------------------

    def create_user(self, username: str, org_id: str | None = None, role: str | None = None) -> dict[str, Any]:
        """Create a new user. Root only. Returns the plaintext key -- shown once."""
        payload: dict[str, Any] = {"username": username}
        if org_id is not None:
            payload["org_id"] = org_id
        if role is not None:
            payload["role"] = role
        return self._call("create-user", payload)

    def create_root_user(self, username: str) -> dict[str, Any]:
        """Create a new root user. Root only. Returns the plaintext key -- shown once."""
        return self._call("create-root-user", {"username": username})

    def create_invite(self, label: str, org_id: str, role: str = "member") -> dict[str, Any]:
        """Create a single-use invite code for self-service signup. Root or org_admin."""
        return self._call("create-invite", {"label": label, "org_id": org_id, "role": role})

    def revoke_invite(self, code: str) -> dict[str, Any]:
        """Revoke an unredeemed invite code. Root only."""
        return self._call("revoke-invite", {"code": code})

    def redeem_invite(self, code: str, username: str) -> dict[str, Any]:
        """Self-serve signup with an invite code. Unauthenticated -- no key needed yet."""
        return self._call("redeem-invite", {"code": code, "username": username})

    def delete_user(self, username: str) -> dict[str, Any]:
        """Delete a user account. Root only."""
        return self._call("delete-user", {"username": username})

    def rotate_key(self) -> dict[str, Any]:
        """Issue yourself a new key; the old one stops working immediately (no grace window)."""
        return self._call("rotate-key", {})

    def get_usage(self, username: str | None = None) -> dict[str, Any]:
        """Current-hour evaluate-heat-risk usage and project counts for yourself
        (or, for a root/org_admin caller, another user if ``username`` is given)."""
        return self._call("get-usage", {"username": username} if username else {})

    # -- organizations & users (root / org_admin) ---------------------------

    def create_org(self, org_id: str, name: str) -> dict[str, Any]:
        """Create an organization. Root only."""
        return self._call("create-org", {"org_id": org_id, "name": name})

    def list_orgs(self) -> dict[str, Any]:
        """List every organization on the platform. Root only."""
        return self._call("list-orgs")

    def list_users(self, org_id: str | None = None) -> dict[str, Any]:
        """List users, optionally scoped to one org. Root or org_admin
        (org_admin is hard-scoped to its own org)."""
        return self._call("list-users", {"org_id": org_id} if org_id else {})

    def set_user_role(self, username: str, role: str) -> dict[str, Any]:
        """Set a user's org role (``org_admin`` | ``member`` | ``read_only``).
        Root or org_admin (own org, may not grant org_admin or touch root)."""
        return self._call("set-user-role", {"username": username, "role": role})

    def set_user_org(self, username: str, org_id: str) -> dict[str, Any]:
        """Move a user to a different org (re-tenants their owned projects too). Root only."""
        return self._call("set-user-org", {"username": username, "org_id": org_id})

    # -- projects: lifecycle -------------------------------------------------

    def create_project(self, project_id: str, geojson: dict[str, Any]) -> dict[str, Any]:
        """Create a new project from a GeoJSON FeatureCollection. Returns 202
        immediately -- poll :meth:`get_project_status` until ``start`` is set,
        then call :meth:`get_metrics` (or :meth:`evaluate_heat_risk`)."""
        return self._call("evaluate-heat-risk", {"project_id": project_id, "json_obj": geojson})

    def evaluate_heat_risk(
        self,
        project_id: str,
        json_obj: dict[str, Any] | None = None,
        limit: int | None = None,
        offset: int | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        include_forecast: bool | None = None,
    ) -> dict[str, Any]:
        """Create a project (pass ``json_obj``) or fetch one page of an
        existing project's daily heat-risk metrics. See :meth:`create_project`
        and :meth:`get_metrics` for the two common cases as separate calls."""
        payload: dict[str, Any] = {"project_id": project_id}
        for key, value in (
            ("json_obj", json_obj),
            ("limit", limit),
            ("offset", offset),
            ("date_from", date_from),
            ("date_to", date_to),
            ("include_forecast", include_forecast),
        ):
            if value is not None:
                payload[key] = value
        return self._call("evaluate-heat-risk", payload)

    def get_metrics(
        self,
        project_id: str,
        limit: int = 500,
        offset: int = 0,
        date_from: str | None = None,
        date_to: str | None = None,
        include_forecast: bool = False,
    ) -> dict[str, Any]:
        """Fetch one page (default up to 500 rows) of an existing, ready
        project's daily heat-risk metrics. See :meth:`iter_metrics` to walk
        every page automatically."""
        return self.evaluate_heat_risk(
            project_id,
            limit=limit,
            offset=offset,
            date_from=date_from,
            date_to=date_to,
            include_forecast=include_forecast,
        )

    def iter_metrics(
        self,
        project_id: str,
        page_size: int = 500,
        date_from: str | None = None,
        date_to: str | None = None,
        include_forecast: bool = False,
    ) -> Iterator[dict[str, Any]]:
        """Yield every metrics row for a project, paging automatically.

        This is the "download all of a project's data" helper: it walks
        ``limit``/``offset`` for you and yields one row dict at a time.

        Example:
            >>> rows = list(client.iter_metrics("2026-demo-nyc-us"))
        """
        offset = 0
        while True:
            page = self.get_metrics(
                project_id,
                limit=page_size,
                offset=offset,
                date_from=date_from,
                date_to=date_to,
                include_forecast=include_forecast,
            )
            rows = page.get("metrics", [])
            yield from rows
            offset += len(rows)
            if not rows or offset >= page.get("total_rows", offset):
                return

    def delete_project(self, project_id: str) -> dict[str, Any]:
        """Permanently delete a project and its data. Owner or root. Cannot be undone."""
        return self._call("delete-project", {"project_id": project_id})

    def get_project_status(self, project_id: str) -> dict[str, Any]:
        """Get a project's metadata (bbox, status, polygon count, WMO reference progress, etc.)."""
        return self._call("get-project-status", {"project_id": project_id})

    def list_projects(self) -> dict[str, Any]:
        """List every project visible to you (your own, your org's, and public projects)."""
        return self._call("list-projects")

    def set_project_inactive(self, project_id: str) -> dict[str, Any]:
        """Mark a project inactive (stops its daily updates). Owner or root."""
        return self._call("set-project-inactive", {"project_id": project_id})

    def set_project_active(self, project_id: str) -> dict[str, Any]:
        """Mark a project active again. Owner or root."""
        return self._call("set-project-active", {"project_id": project_id})

    def set_project_public(self, project_id: str, public: bool) -> dict[str, Any]:
        """Make a project readable cross-org (or revoke that). Root only."""
        return self._call("set-project-public", {"project_id": project_id, "public": public})

    def transfer_project(self, project_id: str, new_owner: str) -> dict[str, Any]:
        """Transfer project ownership to another user (and, cross-org, root required)."""
        return self._call("transfer-project", {"project_id": project_id, "new_owner": new_owner})

    def backfill_project(self, project_id: str, days: int) -> dict[str, Any]:
        """Extend a project's history backwards by ``days`` before its current start date."""
        return self._call("backfill-project", {"project_id": project_id, "days": days})

    # -- downscaling & dataset config (root only) ----------------------------

    def set_project_downscaling(self, project_id: str, enabled: bool) -> dict[str, Any]:
        """Per-project opt-in for neighborhood-resolution downscaling. Root only."""
        return self._call("set-project-downscaling", {"project_id": project_id, "enabled": enabled})

    def set_project_station_blend(self, project_id: str, enabled: bool) -> dict[str, Any]:
        """Per-project opt-out for the Tier-2 nearby-station blend refinement. Root only."""
        return self._call("set-project-station-blend", {"project_id": project_id, "enabled": enabled})

    def set_project_dataset(self, project_id: str, dataset: str) -> dict[str, Any]:
        """Switch a project's ERA5 dataset (``reanalysis-era5-land`` or
        ``reanalysis-era5-single-levels``). Root only; future fetches only."""
        return self._call("set-project-dataset", {"project_id": project_id, "dataset": dataset})

    def rebackfill_era5_history(self, project_id: str) -> dict[str, Any]:
        """Force-overwrite a project's stored ERA5 history at its current dataset. Root only."""
        return self._call("rebackfill-era5-history", {"project_id": project_id})

    def trigger_daily_update(self, project_id: str) -> dict[str, Any]:
        """Enqueue an on-demand daily_update run for one project. Root only."""
        return self._call("trigger-daily-update", {"project_id": project_id})

    def backfill_downscaling(self, project_id: str, date_from: str, date_to: str) -> dict[str, Any]:
        """Write real Tier-1/Tier-2 downscaled rows for an explicit date range. Root only."""
        return self._call(
            "backfill-downscaling",
            {"project_id": project_id, "date_from": date_from, "date_to": date_to},
        )

    def check_served_integrity(
        self, project_id: str, date_from: str | None = None, date_to: str | None = None
    ) -> dict[str, Any]:
        """Read-only: count downscaled rows that don't match their base metrics row. Root only."""
        payload: dict[str, Any] = {"project_id": project_id}
        if date_from is not None:
            payload["date_from"] = date_from
        if date_to is not None:
            payload["date_to"] = date_to
        return self._call("check-served-integrity", payload)

    def repair_grid_base(
        self, project_id: str, date_from: str | None = None, date_to: str | None = None
    ) -> dict[str, Any]:
        """Repair grid_* served columns from their base row where they already match. Root only."""
        payload: dict[str, Any] = {"project_id": project_id}
        if date_from is not None:
            payload["date_from"] = date_from
        if date_to is not None:
            payload["date_to"] = date_to
        return self._call("repair-grid-base", payload)

    def compute_wmo_reference(self, project_id: str, force: bool = False) -> dict[str, Any]:
        """Start computing a project's WMO reference climatology. Owner or root."""
        payload: dict[str, Any] = {"project_id": project_id}
        if force:
            payload["force"] = force
        return self._call("compute-wmo-reference", payload)

    def compute_wmo_utci_reference(self) -> dict[str, Any]:
        """Not implemented server-side yet -- returns a stub response."""
        return self._call("compute-wmo-utci-reference")

    def backfill_utci(self, project_id: str) -> dict[str, Any]:
        """Backfill UTCI/WBGT thermal-comfort columns for a project. Owner or root."""
        return self._call("backfill-utci", {"project_id": project_id})

    def export_ghcn_training(self) -> dict[str, Any]:
        """Export the global ghcn_training table to gzip JSONL on S3 (paged, async). Root only."""
        return self._call("export-ghcn-training", {})

    # -- vulnerability, air quality, LST, nighttime persistence --------------

    def backfill_vulnerability(self, project_id: str) -> dict[str, Any]:
        """Extract vulnerability indicators (RWI, VIIRS, health facilities, etc.) for a project."""
        return self._call("backfill-vulnerability", {"project_id": project_id})

    def get_vulnerability_data(self, project_id: str) -> dict[str, Any]:
        """Fetch a project's per-polygon vulnerability indicators."""
        return self._call("get-vulnerability-data", {"project_id": project_id})

    def resync_population(self, project_id: str) -> dict[str, Any]:
        """Recompute population/timezone/area columns from the project's current GeoJSON."""
        return self._call("resync-population", {"project_id": project_id})

    def backfill_air_quality(self, project_id: str, days: int | None = None) -> dict[str, Any]:
        """Backfill CAMS/OpenAQ air-quality history for a project."""
        payload: dict[str, Any] = {"project_id": project_id}
        if days is not None:
            payload["days"] = days
        return self._call("backfill-air-quality", payload)

    def get_air_quality_data(
        self,
        project_id: str,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 500,
        offset: int = 0,
        include_flagged: bool = False,
    ) -> dict[str, Any]:
        """Fetch daily air-quality rows (PM2.5/PM10/NO2/O3/SO2/CO + AQI) for a project."""
        payload: dict[str, Any] = {
            "project_id": project_id,
            "limit": limit,
            "offset": offset,
            "include_flagged": include_flagged,
        }
        if date_from is not None:
            payload["date_from"] = date_from
        if date_to is not None:
            payload["date_to"] = date_to
        return self._call("get-air-quality-data", payload)

    def delete_air_quality_row(self, project_id: str, name: str, date: str) -> dict[str, Any]:
        """Delete one (name, date) air-quality row. Root only; prefer QC-flagging over deleting."""
        return self._call("delete-air-quality-row", {"project_id": project_id, "name": name, "date": date})

    def backfill_lst(
        self, project_id: str, days: int | None = None, composite_prep: bool | None = None
    ) -> dict[str, Any]:
        """Backfill Landsat land-surface-temperature history. Pass ``days`` OR
        ``composite_prep`` (mutually exclusive), not both."""
        payload: dict[str, Any] = {"project_id": project_id}
        if days is not None:
            payload["days"] = days
        if composite_prep is not None:
            payload["composite_prep"] = composite_prep
        return self._call("backfill-lst", payload)

    def get_lst_data(
        self,
        project_id: str,
        date_from: str | None = None,
        date_to: str | None = None,
        latest_only: bool = False,
        limit: int = 500,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Fetch Landsat land-surface-temperature rows for a project (one row
        per polygon per clear satellite overpass -- not a daily series)."""
        payload: dict[str, Any] = {"project_id": project_id, "latest_only": latest_only}
        if not latest_only:
            payload["limit"] = limit
            payload["offset"] = offset
        if date_from is not None:
            payload["date_from"] = date_from
        if date_to is not None:
            payload["date_to"] = date_to
        return self._call("get-lst-data", payload)

    def get_nighttime_persistence(self, project_id: str) -> dict[str, Any]:
        """Per-tract nighttime-heat streak/density/season-count, each with a coverage flag."""
        return self._call("get-nighttime-persistence", {"project_id": project_id})

    def get_nighttime_vulnerability_overlay(self, project_id: str) -> dict[str, Any]:
        """Top-quartile nighttime persistence x elderly-75+/young-under-5 shortlists."""
        return self._call("get-nighttime-vulnerability-overlay", {"project_id": project_id})

    # -- data availability, provisioning, layers -----------------------------

    def get_data_availability(self, project_id: str) -> dict[str, Any]:
        """Per-project rollup of which data layers exist (population, LST, air
        quality, vulnerability sub-layers, etc.), computed live on every call."""
        return self._call("get-data-availability", {"project_id": project_id})

    def downscaling_fleet_status(self, window_days: int = 7) -> dict[str, Any]:
        """Public-content feed of downscaling model gates and fleet tier mix
        across every public project. Not project-scoped."""
        return self._call("downscaling-fleet-status", {"window_days": window_days})

    def enable_data_layer(self, project_id: str, layer: str) -> dict[str, Any]:
        """Self-serve request to enable one data layer (e.g. ``age_structure``) for a project."""
        return self._call("enable-data-layer", {"project_id": project_id, "layer": layer})

    def get_provisioning_status(self) -> dict[str, Any]:
        """System-wide snapshot of the provisioning queue and 100m WorldPop mirror. Root only."""
        return self._call("get-provisioning-status")

    def list_100m_countries(self) -> dict[str, Any]:
        """List the WorldPop 100m-onboarding registry. Root only."""
        return self._call("list-100m-countries")

    def complete_100m_onboarding(self, iso3: str) -> dict[str, Any]:
        """Mark a country ready for 100m age-structure data. Root only."""
        return self._call("complete-100m-onboarding", {"iso3": iso3})

    def reset_100m_onboarding(self, iso3: str) -> dict[str, Any]:
        """Re-queue a failed/wedged country's 100m onboarding. Root only."""
        return self._call("reset-100m-onboarding", {"iso3": iso3})

    # -- LLM interpretation (experimental) -----------------------------------

    def get_heat_risk_interpretation(self, project_id: str, start_date: str, end_date: str) -> dict[str, Any]:
        """Submit an async LLM interpretation request for a date range. Experimental;
        rate-limited to 5 requests/user/24h. Poll :meth:`get_interpretation_result`."""
        return self._call(
            "get-heat-risk-interpretation",
            {"project_id": project_id, "start_date": start_date, "end_date": end_date},
        )

    def get_interpretation_result(self, llm_req_key: str) -> dict[str, Any]:
        """Poll the result of a :meth:`get_heat_risk_interpretation` request. Experimental."""
        return self._call("get-interpretation-result", {"llm_req_key": llm_req_key})
