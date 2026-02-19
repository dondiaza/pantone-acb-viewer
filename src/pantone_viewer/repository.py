from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

from .acb_parser import Book, parse_acb
from .ase_parser import parse_ase

DEFAULT_PALETTE_FILENAME = "pantone solid coated-v4.acb"
FIXED_ACHROMATIC_BY_HEX = {
    "#FFFFFF": "BLANCO",
    "#000000": "NEGRO",
}


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
            path, book = self._require_book(book_id)
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

    def get_default_palette_id(self) -> str | None:
        with self._lock:
            error = self._refresh_id_map()
            if error:
                return None
            return self._pick_default_palette_id(self._id_to_path)

    def get_palette_title(self, book_id: str) -> str:
        with self._lock:
            error = self._refresh_id_map()
            if error:
                raise FileNotFoundError(error)
            path = self._id_to_path.get(book_id)
            if path is None:
                raise KeyError(book_id)
            return path.stem

    def search_by_hex(
        self, query: str, book_id: str | None = None, limit: int = 200
    ) -> dict[str, Any]:
        with self._lock:
            error = self._refresh_id_map()
            if error:
                raise FileNotFoundError(error)

            normalized_hex = _normalize_hex(query)
            target_rgb = _hex_to_rgb(normalized_hex)

            scoped_books = self._resolve_book_scope(book_id)
            scope_label = (
                scoped_books[0][1].stem
                if len(scoped_books) == 1
                else f"Todas las paletas ({len(scoped_books)})"
            )
            scope_book_id = scoped_books[0][0] if len(scoped_books) == 1 else None
            forced_match = _forced_achromatic_item_from_hex(
                normalized_hex=normalized_hex,
                scope_book_id=scope_book_id,
                scope_book_title=scoped_books[0][1].stem if len(scoped_books) == 1 else "Coincidencia fija",
                scope_filename=scoped_books[0][1].name if len(scoped_books) == 1 else "",
            )
            if forced_match is not None:
                return {
                    "query": normalized_hex,
                    "scope": scope_label,
                    "scope_book_id": scope_book_id,
                    "exact_count": 1,
                    "exact_matches": [forced_match],
                    "nearest": [forced_match | {"distance": 0}],
                }

            exact_matches: list[dict[str, Any]] = []
            nearest: list[tuple[int, dict[str, Any]]] = []

            for scoped_id, path in scoped_books:
                entry = self._load_cached(scoped_id, path)
                if entry.error or entry.book is None:
                    continue

                for color in entry.book.colors:
                    item = {
                        "book_id": scoped_id,
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
                "scope": scope_label,
                "scope_book_id": scope_book_id,
                "exact_count": len(exact_matches),
                "exact_matches": exact_matches[:limit],
                "nearest": nearest_items,
            }

    def nearest_in_book(self, target_rgb: tuple[int, int, int], book_id: str) -> dict[str, Any]:
        with self._lock:
            path, book = self._require_book(book_id)
            forced_match = _forced_achromatic_item_from_rgb(
                target_rgb=target_rgb,
                scope_book_id=book_id,
                scope_book_title=path.stem,
                scope_filename=path.name,
            )
            if forced_match is not None:
                return forced_match | {"distance": 0}

            nearest: tuple[int, Any] | None = None
            for color in book.colors:
                distance = _rgb_distance(target_rgb, _hex_to_rgb(color.hex))
                if nearest is None or distance < nearest[0]:
                    nearest = (distance, color)

            if nearest is None:
                raise RuntimeError(f"No hay colores disponibles en la paleta: {book_id}")

            distance, color = nearest
            return {
                "book_id": book_id,
                "book_title": path.stem,
                "filename": path.name,
                "name": color.name,
                "code": color.code or None,
                "hex": color.hex,
                "distance": distance,
            }

    def _require_book(self, book_id: str) -> tuple[Path, Book]:
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
        return path, entry.book

    def _resolve_book_scope(self, book_id: str | None) -> list[tuple[str, Path]]:
        if book_id:
            path = self._id_to_path.get(book_id)
            if path is None:
                raise KeyError(book_id)
            return [(book_id, path)]
        return list(self._id_to_path.items())

    def _refresh_id_map(self) -> str | None:
        if not self.acb_dir.exists():
            self._id_to_path = {}
            return f"No se encontro el directorio de muestras: {self.acb_dir}"
        if not self.acb_dir.is_dir():
            self._id_to_path = {}
            return f"La ruta de muestras no es un directorio: {self.acb_dir}"

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
                raise ValueError(f"Extension de archivo no soportada: {path.suffix}")

            entry = CacheEntry(path=path, mtime=mtime, book=book, error=None)
        except Exception as exc:
            entry = CacheEntry(path=path, mtime=mtime, book=None, error=str(exc))

        self._cache[book_id] = entry
        return entry

    @staticmethod
    def _pick_default_palette_id(id_to_path: dict[str, Path]) -> str | None:
        for book_id, path in id_to_path.items():
            if path.name.lower() == DEFAULT_PALETTE_FILENAME:
                return book_id

        for book_id, path in id_to_path.items():
            if path.suffix.lower() == ".acb":
                return book_id

        for book_id in id_to_path:
            return book_id

        return None

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
        raise ValueError("Formato HEX invalido. Usa #RRGGBB o #RGB.")

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


def _forced_achromatic_item_from_hex(
    normalized_hex: str,
    scope_book_id: str | None,
    scope_book_title: str,
    scope_filename: str,
) -> dict[str, Any] | None:
    name = FIXED_ACHROMATIC_BY_HEX.get(normalized_hex.upper())
    if name is None:
        return None

    return {
        "book_id": scope_book_id,
        "book_title": scope_book_title,
        "filename": scope_filename,
        "name": name,
        "code": None,
        "hex": normalized_hex.upper(),
    }


def _forced_achromatic_item_from_rgb(
    target_rgb: tuple[int, int, int],
    scope_book_id: str | None,
    scope_book_title: str,
    scope_filename: str,
) -> dict[str, Any] | None:
    if target_rgb == (255, 255, 255):
        fixed_hex = "#FFFFFF"
    elif target_rgb == (0, 0, 0):
        fixed_hex = "#000000"
    else:
        return None

    return _forced_achromatic_item_from_hex(
        normalized_hex=fixed_hex,
        scope_book_id=scope_book_id,
        scope_book_title=scope_book_title,
        scope_filename=scope_filename,
    )
