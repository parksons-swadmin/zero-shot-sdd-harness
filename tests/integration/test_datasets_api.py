import io

import pytest


def _csv_bytes(rows: int = 20) -> bytes:
    lines = ["name,signup_date,revenue,region"]
    for i in range(rows):
        lines.append(f"User {i}, 01/0{(i % 9) + 1}/2024, ${1000 + i}.50, West")
    return ("\n".join(lines)).encode("utf-8")


def test_upload_then_get_round_trip(api_client, tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    import config.settings as settings_module
    settings_module._settings = None

    files = {"file": ("leads_export.csv", _csv_bytes(20), "text/csv")}
    resp = api_client.post("/datasets", files=files)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["error"] is None
    data = body["data"]
    assert data["filename"] == "leads_export.csv"
    assert data["row_count"] == 20
    assert data["column_count"] == 4
    assert data["status"] == "ready"
    assert len(data["profile"]["columns"]) == 4
    col_names = {c["name"] for c in data["profile"]["columns"]}
    assert col_names == {"name", "signup_date", "revenue", "region"}
    assert isinstance(data["cleaning_report"]["issues"], list)

    dataset_id = data["dataset_id"]
    get_resp = api_client.get(f"/datasets/{dataset_id}")
    assert get_resp.status_code == 200
    get_data = get_resp.json()["data"]
    assert get_data["dataset_id"] == dataset_id
    assert get_data["row_count"] == 20


def test_get_unknown_dataset_returns_404(api_client):
    resp = api_client.get("/datasets/does-not-exist")
    assert resp.status_code == 404
    body = resp.json()
    assert body["detail"]["code"] == "NOT_FOUND"


def test_upload_unparseable_file_returns_400(api_client, tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    import config.settings as settings_module
    settings_module._settings = None

    files = {"file": ("not_a_csv.bin", b"\x00\x01\x02\x03\xff\xfe", "application/octet-stream")}
    resp = api_client.post("/datasets", files=files)
    assert resp.status_code == 400
    body = resp.json()
    assert body["detail"]["code"] == "UNPARSEABLE_FILE"


def test_upload_exceeding_max_bytes_returns_413(api_client, tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AGENT_MAX_UPLOAD_BYTES", "100")
    import config.settings as settings_module
    settings_module._settings = None

    big_csv = _csv_bytes(50)
    assert len(big_csv) > 100
    files = {"file": ("big.csv", big_csv, "text/csv")}
    resp = api_client.post("/datasets", files=files)
    assert resp.status_code == 413
    body = resp.json()
    assert body["detail"]["code"] == "FILE_TOO_LARGE"

    # no partial file left behind
    uploads_dir = tmp_path / "uploads"
    if uploads_dir.exists():
        leftover = list(uploads_dir.glob("**/*"))
        leftover_files = [p for p in leftover if p.is_file()]
        assert leftover_files == []
