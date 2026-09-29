"""Unit tests for HeatReadyClient using mocked HTTP responses (no network, no credentials)."""

from __future__ import annotations

import time

import pytest
import responses

from heatready import DEFAULT_BASE_URL, HeatReadyClient, HeatReadyError

EVALUATE_URL = f"{DEFAULT_BASE_URL}/evaluate"


@pytest.fixture
def client() -> HeatReadyClient:
    return HeatReadyClient(username="alice", key="test-key", retry_delays=(0, 0, 0))


@responses.activate
def test_status_is_unauthenticated(client: HeatReadyClient) -> None:
    responses.add(
        responses.POST,
        EVALUATE_URL,
        json={"status": "ok", "systems": {"database": "ok", "era5_pipeline": "ok"}, "daily_update_dlq_depth": 0},
        status=200,
    )
    result = client.status()
    assert result["status"] == "ok"
    sent_body = responses.calls[0].request.body
    assert b'"action": "status"' in sent_body or b'"action":"status"' in sent_body


@responses.activate
def test_list_projects_sends_credentials(client: HeatReadyClient) -> None:
    responses.add(responses.POST, EVALUATE_URL, json={"projects": []}, status=200)
    client.list_projects()
    import json

    sent = json.loads(responses.calls[0].request.body)
    assert sent["username"] == "alice"
    assert sent["key"] == "test-key"
    assert sent["action"] == "list-projects"
    assert "payload" not in sent  # list-projects has no payload


@responses.activate
def test_get_project_status_payload(client: HeatReadyClient) -> None:
    responses.add(
        responses.POST,
        EVALUATE_URL,
        json={"project_id": "2026-demo-nyc-us", "status": "active", "polygon_count": 188},
        status=200,
    )
    result = client.get_project_status("2026-demo-nyc-us")
    assert result["status"] == "active"
    import json

    sent = json.loads(responses.calls[0].request.body)
    assert sent["payload"] == {"project_id": "2026-demo-nyc-us"}


@responses.activate
def test_error_response_raises_heatready_error(client: HeatReadyClient) -> None:
    responses.add(
        responses.POST,
        EVALUATE_URL,
        json={"error": "Project 'nope' not found", "code": "project_not_found"},
        status=404,
    )
    with pytest.raises(HeatReadyError) as exc_info:
        client.get_project_status("nope")
    assert exc_info.value.code == "project_not_found"
    assert exc_info.value.status_code == 404


@responses.activate
def test_invalid_credentials_raises_with_code(client: HeatReadyClient) -> None:
    responses.add(
        responses.POST,
        EVALUATE_URL,
        json={"error": "Invalid username or key", "code": "invalid_credentials"},
        status=401,
    )
    with pytest.raises(HeatReadyError) as exc_info:
        client.list_projects()
    assert exc_info.value.code == "invalid_credentials"


@responses.activate
def test_retries_on_503_then_succeeds(client: HeatReadyClient) -> None:
    responses.add(
        responses.POST,
        EVALUATE_URL,
        json={"error": "Database unavailable, please retry in a moment", "code": "database_unavailable"},
        status=503,
    )
    responses.add(responses.POST, EVALUATE_URL, json={"projects": []}, status=200)
    result = client.list_projects()
    assert result == {"projects": []}
    assert len(responses.calls) == 2


@responses.activate
def test_503_exhausts_retries_and_raises(client: HeatReadyClient) -> None:
    for _ in range(1 + len(client.retry_delays)):
        responses.add(
            responses.POST,
            EVALUATE_URL,
            json={"error": "Database unavailable, please retry in a moment", "code": "database_unavailable"},
            status=503,
        )
    with pytest.raises(HeatReadyError) as exc_info:
        client.list_projects()
    assert exc_info.value.status_code == 503
    assert len(responses.calls) == 1 + len(client.retry_delays)


@responses.activate
def test_retry_delays_are_honored(client: HeatReadyClient) -> None:
    client.retry_delays = (0.01, 0.02)
    responses.add(
        responses.POST,
        EVALUATE_URL,
        json={"error": "Database unavailable", "code": "database_unavailable"},
        status=503,
    )
    responses.add(responses.POST, EVALUATE_URL, json={"projects": []}, status=200)
    start = time.monotonic()
    client.list_projects()
    elapsed = time.monotonic() - start
    assert elapsed >= 0.01


@responses.activate
def test_create_project_sends_geojson(client: HeatReadyClient) -> None:
    responses.add(
        responses.POST,
        EVALUATE_URL,
        json={"project_id": "test-project", "status": "initializing", "estimated_minutes": 15},
        status=202,
    )
    geojson = {"type": "FeatureCollection", "features": []}
    result = client.create_project("test-project", geojson)
    assert result["status"] == "initializing"
    import json

    sent = json.loads(responses.calls[0].request.body)
    assert sent["payload"]["json_obj"] == geojson


@responses.activate
def test_iter_metrics_pages_through_all_rows(client: HeatReadyClient) -> None:
    page_1 = {
        "project_id": "p",
        "total_rows": 3,
        "limit": 2,
        "offset": 0,
        "metrics": [{"name": "a", "date": "2026-01-01"}, {"name": "a", "date": "2026-01-02"}],
        "polygon_coverage": {},
    }
    page_2 = {
        "project_id": "p",
        "total_rows": 3,
        "limit": 2,
        "offset": 2,
        "metrics": [{"name": "a", "date": "2026-01-03"}],
        "polygon_coverage": {},
    }
    responses.add(responses.POST, EVALUATE_URL, json=page_1, status=200)
    responses.add(responses.POST, EVALUATE_URL, json=page_2, status=200)

    rows = list(client.iter_metrics("p", page_size=2))
    assert len(rows) == 3
    assert [r["date"] for r in rows] == ["2026-01-01", "2026-01-02", "2026-01-03"]
    assert len(responses.calls) == 2


@responses.activate
def test_iter_metrics_stops_on_empty_page(client: HeatReadyClient) -> None:
    responses.add(
        responses.POST,
        EVALUATE_URL,
        json={"project_id": "p", "total_rows": 0, "limit": 500, "offset": 0, "metrics": [], "polygon_coverage": {}},
        status=200,
    )
    rows = list(client.iter_metrics("p"))
    assert rows == []
    assert len(responses.calls) == 1


@responses.activate
def test_get_lst_data_latest_only_omits_pagination_fields(client: HeatReadyClient) -> None:
    responses.add(
        responses.POST,
        EVALUATE_URL,
        json={"project_id": "p", "lst": []},
        status=200,
    )
    client.get_lst_data("p", latest_only=True)
    import json

    sent = json.loads(responses.calls[0].request.body)
    assert "limit" not in sent["payload"]
    assert "offset" not in sent["payload"]


@responses.activate
def test_backfill_lst_days_and_composite_prep_are_mutually_optional(client: HeatReadyClient) -> None:
    responses.add(
        responses.POST,
        EVALUATE_URL,
        json={"project_id": "p", "status": "backfilling", "message": "..."},
        status=202,
    )
    client.backfill_lst("p", days=90)
    import json

    sent = json.loads(responses.calls[0].request.body)
    assert sent["payload"] == {"project_id": "p", "days": 90}
