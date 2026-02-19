from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

from .acb_parser import Book, parse_acb
from .ase_parser import parse_ase


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
                file_format = path.suffix.lstrip(".").upper()
                if entry.error:
                    books.append(
                        {
                            "id": book_id,
                            "filename": path.name,
                            "title": path.stem,
                            "format": file_format,
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
                        "title": path.stem,
                        "format": file_format,
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
                "title": path.stem,
                "filename": path.name,
                "format": path.suffix.lstrip(".").upper(),
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

    def search_by_hex(self, query: str, limit: int = 200) -> dict[str, Any]:
        with self._lock:
            error = self._refresh_id_map()
            if error:
                raise FileNotFoundError(error)

            normalized_hex = _normalize_hex(query)
            target_rgb = _hex_to_rgb(normalized_hex)

            exact_matches: list[dict[str, Any]] = []
            nearest: list[tuple[int, dict[str, Any]]] = []

            for book_id, path in self._id_to_path.items():
                entry = self._load_cached(book_id, path)
                if entry.error or entry.book is None:
                    continue

                for color in entry.book.colors:
                    item = {
                        "book_id": book_id,
                        "book_title": path.stem,
                        "filename": path.name,
                        "name": color.name,
                        "code": color.code or None,
                        "hex": color.hex,
                    }

                    if color.hex.upper() == normalized_hex:
                        exact_matches.append(item)

                    distance = _rgb_distance(target_rgb, _hex_to_rgb(color.hex))
                    nearest.append((distance, item))

            nearest.sort(key=lambda row: row[0])
            nearest_items = [item | {"distance": distance} for distance, item in nearest[:limit]]

            return {
                "query": normalized_hex,
                "exact_count": len(exact_matches),
                "exact_matches": exact_matches[:limit],
                "nearest": nearest_items,
            }

    def _refresh_id_map(self) -> str | None:
        if not self.acb_dir.exists():
            self._id_to_path = {}
            return f"Swatch directory not found: {self.acb_dir}"
        if not self.acb_dir.is_dir():
            self._id_to_path = {}
            return f"Swatch path is not a directory: {self.acb_dir}"

        files = sorted(
            [*self.acb_dir.glob("*.acb"), *self.acb_dir.glob("*.ase")],
            key=lambda path: path.name.lower(),
        )

        id_to_path: dict[str, Path] = {}
        used_ids: set[str] = set()
        for path in files:
            seed = f"{path.stem}-{path.suffix.lstrip('.')}"
            book_id = self._unique_slug(seed, used_ids)
            id_to_path[book_id] = path

        self._id_to_path = id_to_path
        return None

    def _load_cached(self, book_id: str, path: Path) -> CacheEntry:
        mtime = path.stat().st_mtime
        cached = self._cache.get(book_id)
        if cached and cached.path == path and cached.mtime == mtime:
            return cached

        try:
            suffix = path.suffix.lower()
            if suffix == ".acb":
                book = parse_acb(path)
            elif suffix == ".ase":
                book = parse_ase(path)
            else:
                raise ValueError(f"Unsupported file extension: {path.suffix}")

            entry = CacheEntry(path=path, mtime=mtime, book=book, error=None)
        except Exception as exc:
            entry = CacheEntry(path=path, mtime=mtime, book=None, error=str(exc))

        self._cache[book_id] = entry
        return entry

    @staticmethod
    def _unique_slug(seed: str, used_ids: set[str]) -> str:
        base = re.sub(r"[^a-zA-Z0-9]+", "-", seed.strip().lower()).strip("-")
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


def _normalize_hex(value: str) -> str:
    stripped = value.strip().upper()
    if stripped.startswith("#"):
        stripped = stripped[1:]

    if len(stripped) == 3 and all(ch in "0123456789ABCDEF" for ch in stripped):
        stripped = "".join(ch * 2 for ch in stripped)

    if len(stripped) != 6 or any(ch not in "0123456789ABCDEF" for ch in stripped):
        raise ValueError("Invalid HEX format. Use #RRGGBB or #RGB.")

    return f"#{stripped}"


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _rgb_distance(left: tuple[int, int, int], right: tuple[int, int, int]) -> int:
    return (
        (left[0] - right[0]) * (left[0] - right[0])
        + (left[1] - right[1]) * (left[1] - right[1])
        + (left[2] - right[2]) * (left[2] - right[2])
    )
