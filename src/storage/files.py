"""Local filesystem storage for uploaded/cleaned dataset files.

All paths are rooted under `AGENT_DATA_DIR` (default `./data`) — never written
anywhere outside that directory. See spec/architecture.md -> File Storage Layout.
"""
from pathlib import Path

import pandas as pd
from fastapi import UploadFile

from config.settings import get_settings


def _data_dir() -> Path:
    return Path(get_settings().data_dir).resolve()


def uploads_dir(dataset_id: str) -> Path:
    d = _data_dir() / "uploads" / dataset_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def original_path_for(dataset_id: str, ext: str) -> Path:
    return uploads_dir(dataset_id) / f"original{ext}"


def cleaned_path_for(dataset_id: str) -> Path:
    return uploads_dir(dataset_id) / "cleaned.parquet"


def save_upload_stream(dataset_id: str, ext: str, upload: UploadFile, max_bytes: int) -> tuple[Path, int]:
    """Stream an UploadFile to disk in chunks, enforcing max_bytes.

    Never fully buffers the file in memory. Raises ValueError if the size
    cap is exceeded before the write completes; the partial file is removed.
    """
    dest = original_path_for(dataset_id, ext)
    total = 0
    chunk_size = 1024 * 1024
    try:
        with open(dest, "wb") as out:
            while True:
                chunk = upload.file.read(chunk_size)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError("upload exceeds AGENT_MAX_UPLOAD_BYTES")
                out.write(chunk)
    except ValueError:
        dest.unlink(missing_ok=True)
        raise
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    return dest, total


def save_cleaned_parquet(dataset_id: str, df: pd.DataFrame) -> Path:
    dest = cleaned_path_for(dataset_id)
    df.to_parquet(dest, index=False)
    return dest


def remove_dataset_files(dataset_id: str) -> None:
    """Best-effort cleanup of a dataset's directory (e.g. on hard failure)."""
    import shutil

    d = _data_dir() / "uploads" / dataset_id
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
