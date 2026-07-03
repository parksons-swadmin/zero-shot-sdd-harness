"""Local filesystem storage for promoted export/derived datasets (Phase 3a).

An analysis run may assign a full derived DataFrame to `export_df`; the sandbox
writes it to a temp parquet (see `execution/sandbox.py`) and `graph/finalize`
calls `promote_export` here to move it into a stable per-query-result location
that a derived `Dataset` can point at. All paths are rooted under
`AGENT_DATA_DIR` (default `./data`) — never written outside it. The full-row
export lives ONLY on local disk and never enters a prompt/answer payload; it
crosses to the client solely via the explicit `GET /query-results/{id}/export`
download (owned by another slice). See spec/architecture.md -> File Storage.
"""
from pathlib import Path

import pandas as pd

from config.settings import get_settings


def _data_dir() -> Path:
    return Path(get_settings().data_dir).resolve()


def exports_dir(query_result_id: str) -> Path:
    d = _data_dir() / "exports" / query_result_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def export_csv_path(query_result_id: str) -> Path:
    return exports_dir(query_result_id) / "export.csv"


def export_parquet_path(query_result_id: str) -> Path:
    return exports_dir(query_result_id) / "export.parquet"


def promote_export(query_result_id: str, temp_path: str) -> dict:
    """Read the temp parquet written by the sandbox, write a stable
    `export.csv` + `export.parquet` under `exports/<query_result_id>/`, delete
    the temp file, and return {csv_path, parquet_path, row_count, column_count}.

    The full derived rows are written to local disk only — this function never
    returns rows and never surfaces them to a prompt.
    """
    df = pd.read_parquet(temp_path)

    csv_path = export_csv_path(query_result_id)
    parquet_path = export_parquet_path(query_result_id)
    df.to_csv(csv_path, index=False)
    df.to_parquet(parquet_path, index=False)

    Path(temp_path).unlink(missing_ok=True)

    return {
        "csv_path": str(csv_path),
        "parquet_path": str(parquet_path),
        "row_count": int(len(df)),
        "column_count": int(df.shape[1]),
    }
