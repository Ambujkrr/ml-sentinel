import csv
import io
from pathlib import PurePosixPath

import pandas as pd
from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.domain import Dataset, DatasetProfile
from app.monitoring.profiling import profile_dataset
from app.services.storage import LocalStorage


def parse_csv(content: bytes) -> pd.DataFrame:
    settings = get_settings()
    if len(content) > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "CSV exceeds the configured upload limit")
    try:
        text = content.decode("utf-8-sig")
        if "\x00" in text:
            raise ValueError("Binary input")
        rows = csv.reader(io.StringIO(text, newline=""), strict=True)
        header = next(rows)
        if not header or any(not name.strip() for name in header):
            raise ValueError("Column names must be non-empty")
        if len(set(header)) != len(header):
            raise ValueError("Duplicate column names")
        if len(header) > settings.MAX_DATASET_COLUMNS:
            raise HTTPException(413, "CSV has too many columns")
        count = 0
        for row in rows:
            if not row:
                continue
            if len(row) != len(header):
                raise ValueError("Inconsistent row width")
            count += 1
            if count > settings.MAX_DATASET_ROWS:
                raise HTTPException(413, "CSV has too many rows")
        if not count:
            raise ValueError("CSV has no data rows")
        frame = pd.read_csv(io.StringIO(text), low_memory=False)
        if frame.empty:
            raise ValueError("CSV has no data")
        return frame
    except (UnicodeError, csv.Error, StopIteration, ValueError,
            pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise HTTPException(400, "Invalid CSV: use UTF-8, unique column names and consistent, non-empty data rows") from exc


def ingest_dataset(db: Session, storage: LocalStorage, model_id: str,
                   name: str, dataset_type: str, upload: UploadFile) -> Dataset:
    filename = PurePosixPath((upload.filename or "dataset.csv").replace("\\", "/")).name
    if not filename.lower().endswith(".csv"):
        raise HTTPException(400, "Upload a .csv file")
    content = upload.file.read(get_settings().MAX_UPLOAD_BYTES + 1)
    frame = parse_csv(content)
    profile = profile_dataset(frame)
    key = storage.save(content)
    dataset = Dataset(model_id=model_id, name=name, dataset_type=dataset_type,
                      file_name=filename[:255], file_path=key,
                      row_count=len(frame), column_count=len(frame.columns))
    try:
        db.add(dataset)
        db.flush()
        db.add(DatasetProfile(dataset_id=dataset.id, report=profile))
        db.commit()
    except Exception:
        db.rollback()
        storage.delete(key)
        raise
    return dataset
