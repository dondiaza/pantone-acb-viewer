from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

from .acb_parser import Book, parse_acb


@dataclass(slots=True)
class CacheEntry:
    path: Path
    mtime: float
    book: Book | None
    error: str | None


class ACBRepository:
    def __init__(self, acb_dir: str | Path) -> None:
        self.acb_dir = Path(acb_dir)
        self._cache: dict[str, CacheEntry] = {}
        self._id_to_path: dict[str, Path] = {}
        self._lock = RLock()

    def list_books(self) -> tuple[list[dict[str, Any]], str | None]:
        with self._lock:
            error = self._refresh_id_map()
            if error:
                return [], error

            books: list[dict[str, Any]] = []
            for book_id, path in self._id_to_path.items():
                entry = self._load_cached(book_id, path)
                if entry.error:
                    books.append(
                        {
                            "id": book_id,
                            "filename": path.name,
                            "title": path.stem,
                            "color_count": None,
                            "colorspace": None,
                            "error": entry.error,
                        }
                    )
                    continue

                assert entry.book is not None
                books.append(
                    {
                        "id": book_id,
                        "filename": path.name,
                        "title": entry.book.title or path.stem,
                        "color_count": len(entry.book.colors),
                        "colorspace": entry.book.colorspace_name,
                    }
                )
            return books, None

    def get_book_details(self, book_id: str) -> dict[str, Any]:
        with self._lock:
            error = self._refresh_id_map()
            if error:
                raise FileNotFoundError(error)

            path = self._id_to_path.get(book_id)
            if path is None:
                raise KeyError(book_id)

            entry = self._load_cached(book_id, path)
            if entry.error:
                raise RuntimeError(entry.error)
            assert entry.book is not None
            book = entry.book

            return {
                "id": book_id,
                "title": book.title or path.stem,
                "filename": path.name,
                "colorspace": book.colorspace_name,
                "colors": [
                    {
                        "name": color.name,
                        "code": color.code or None,
                        "hex": color.hex,
                    }
                    for color in book.colors
                ],
            }

    def _refresh_id_map(self) -> str | None:
        if not self.acb_dir.exists():
            self._id_to_path = {}
            return f"ACB directory not found: {self.acb_dir}"
        if not self.acb_dir.is_dir():
            self._id_to_path = {}
            return f"ACB path is not a directory: {self.acb_dir}"

        files = sorted(self.acb_dir.glob("*.acb"), key=lambda path: path.name.lower())
        id_to_path: dict[str, Path] = {}
        used_ids: set[str] = set()
        for path in files:
            book_id = self._unique_slug(path.stem, used_ids)
            id_to_path[book_id] = path

        self._id_to_path = id_to_path
        return None

    def _load_cached(self, book_id: str, path: Path) -> CacheEntry:
        mtime = path.stat().st_mtime
        cached = self._cache.get(book_id)
        if cached and cached.path == path and cached.mtime == mtime:
            return cached

        try:
            book = parse_acb(path)
            entry = CacheEntry(path=path, mtime=mtime, book=book, error=None)
        except Exception as exc:
            entry = CacheEntry(path=path, mtime=mtime, book=None, error=str(exc))

        self._cache[book_id] = entry
        return entry

    @staticmethod
    def _unique_slug(stem: str, used_ids: set[str]) -> str:
        base = re.sub(r"[^a-zA-Z0-9]+", "-", stem.strip().lower()).strip("-")
        if not base:
            base = "book"

        if base not in used_ids:
            used_ids.add(base)
            return base

        index = 2
        while True:
            candidate = f"{base}-{index}"
            if candidate not in used_ids:
                used_ids.add(candidate)
                return candidate
            index += 1
