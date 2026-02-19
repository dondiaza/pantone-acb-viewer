from __future__ import annotations

import json
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from threading import RLock


@dataclass(slots=True)
class UploadSession:
    upload_id: str
    filename: str
    created_at: float
    size: int


class UploadStore:
    def __init__(self, base_dir: str | Path | None = None) -> None:
        if base_dir is None:
            base_dir = Path(tempfile.gettempdir()) / "pantone_uploads"
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def create_session(self, filename: str) -> UploadSession:
        with self._lock:
            self.cleanup_old()
            upload_id = uuid.uuid4().hex
            session = UploadSession(
                upload_id=upload_id,
                filename=filename or "archivo",
                created_at=time.time(),
                size=0,
            )
            self._write_meta(session)
            self._data_path(upload_id).write_bytes(b"")
            return session

    def append_chunk(self, upload_id: str, chunk: bytes) -> UploadSession:
        if not chunk:
            return self.get_session(upload_id)

        with self._lock:
            session = self.get_session(upload_id)
            with self._data_path(upload_id).open("ab") as handle:
                handle.write(chunk)
            session.size += len(chunk)
            self._write_meta(session)
            return session

    def finalize(self, upload_id: str) -> tuple[UploadSession, bytes]:
        with self._lock:
            session = self.get_session(upload_id)
            data_path = self._data_path(upload_id)
            data = data_path.read_bytes()
            self._delete_session(upload_id)
            return session, data

    def get_session(self, upload_id: str) -> UploadSession:
        meta_path = self._meta_path(upload_id)
        if not meta_path.exists():
            raise KeyError(upload_id)
        raw = json.loads(meta_path.read_text(encoding="utf-8"))
        return UploadSession(
            upload_id=raw["upload_id"],
            filename=raw["filename"],
            created_at=float(raw["created_at"]),
            size=int(raw["size"]),
        )

    def cleanup_old(self, max_age_seconds: int = 3600) -> None:
        now = time.time()
        for meta_path in self.base_dir.glob("*.json"):
            try:
                raw = json.loads(meta_path.read_text(encoding="utf-8"))
                created_at = float(raw.get("created_at", now))
                upload_id = str(raw.get("upload_id", ""))
            except Exception:
                continue

            if not upload_id:
                continue
            if now - created_at > max_age_seconds:
                self._delete_session(upload_id)

    def _write_meta(self, session: UploadSession) -> None:
        payload = {
            "upload_id": session.upload_id,
            "filename": session.filename,
            "created_at": session.created_at,
            "size": session.size,
        }
        self._meta_path(session.upload_id).write_text(json.dumps(payload), encoding="utf-8")

    def _delete_session(self, upload_id: str) -> None:
        meta_path = self._meta_path(upload_id)
        data_path = self._data_path(upload_id)
        if meta_path.exists():
            meta_path.unlink()
        if data_path.exists():
            data_path.unlink()

    def _meta_path(self, upload_id: str) -> Path:
        return self.base_dir / f"{upload_id}.json"

    def _data_path(self, upload_id: str) -> Path:
        return self.base_dir / f"{upload_id}.bin"

