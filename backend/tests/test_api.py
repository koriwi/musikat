"""HTTP smoke tests for the FastAPI app (no external catalog calls)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client() -> TestClient:
    from app import app

    return TestClient(app)


def test_health(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "healthy"
    assert "default_metadata_provider" in data
    assert "navidrome_path" in data


def test_formats(client: TestClient) -> None:
    r = client.get("/api/formats")
    assert r.status_code == 200
    data = r.json()
    assert "formats" in data
    assert "qualities" in data
    values = {f["value"] for f in data["formats"]}
    assert "mp3" in values and "flac" in values


def test_metadata_providers(client: TestClient) -> None:
    r = client.get("/api/metadata/providers")
    assert r.status_code == 200
    data = r.json()
    assert data["default"] in ("deezer", "spotify")
    ids = {p["id"] for p in data["providers"]}
    assert "deezer" in ids and "spotify" in ids


def test_root_returns_html(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")


def test_search_invalid_provider(client: TestClient) -> None:
    r = client.post(
        "/api/search",
        json={"query": "test", "provider": "not-a-provider"},
    )
    assert r.status_code == 400
    assert "provider" in r.json()["detail"].lower()


def test_list_jobs(client: TestClient) -> None:
    r = client.get("/api/jobs")
    assert r.status_code == 200
    data = r.json()
    assert "jobs" in data
    assert isinstance(data["jobs"], list)


def test_cancel_unknown_job_returns_404(client: TestClient) -> None:
    r = client.post("/api/download/cancel/nonexistent-job-id")
    assert r.status_code == 404


def test_cancel_queued_job(client: TestClient) -> None:
    from utils.job_store import _db, get_job, upsert_job

    job_id = "test-cancel-job"
    upsert_job(job_id, status="queued", message="Queued for test")
    try:
        r = client.post(f"/api/download/cancel/{job_id}")
        assert r.status_code == 200
        assert r.json()["status"] == "cancelled"
        assert get_job(job_id)["status"] == "cancelled"

        r2 = client.post(f"/api/download/cancel/{job_id}")
        assert r2.status_code == 404
    finally:
        conn = _db()
        try:
            conn.execute("DELETE FROM download_jobs WHERE job_id = ?", (job_id,))
            conn.commit()
        finally:
            conn.close()


def test_album_aggregate_counts_cancelled_as_terminal() -> None:
    from utils.job_store import _db, get_album_aggregate, upsert_job

    album_id = "test-album-agg"
    for tid in ("test-album-agg-t1", "test-album-agg-t2"):
        upsert_job(tid, status="completed", message="done", album_id=album_id)
    upsert_job("test-album-agg-t3", status="cancelled", message="cancelled", album_id=album_id)
    try:
        agg = get_album_aggregate(album_id)
        assert agg["status"] == "completed"
        assert agg["cancelled_tracks"] == 1
        assert agg["current_track"] is None
    finally:
        conn = _db()
        try:
            conn.execute("DELETE FROM download_jobs WHERE album_id = ?", (album_id,))
            conn.commit()
        finally:
            conn.close()
