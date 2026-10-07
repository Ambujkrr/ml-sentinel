"""Local blob storage. Services use these methods so object storage can replace it."""
from pathlib import Path
from uuid import uuid4

from app.core.config import get_settings


class LocalStorage:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if path.parent != self.root or Path(key).name != key:
            raise ValueError("Invalid storage key")
        return path

    def save(self, content: bytes) -> str:
        self.root.mkdir(parents=True, exist_ok=True)
        key = f"{uuid4()}.csv"
        path = self._path(key)
        try:
            with path.open("xb") as destination:
                destination.write(content)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return key

    def read(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


def get_storage() -> LocalStorage:
    return LocalStorage(get_settings().UPLOAD_DIR)
