from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

from .acb_parser import Book, parse_acb
from .ase_parser import parse_ase
from .color_convert import (
    delta_e_ciede2000,
    parse_color_input,
    reliability_label,
    rgb_to_cmyk,
    rgb_to_hex,
    rgb_to_lab_d50,
    rgb_to_lab_d65,
)

DEFAULT_PALETTE_FILENAME = "pantone solid coated-v4.acb"
FIXED_ACHROMATIC_BY_HEX = {
    "#FFFFFF": "BLANCO",
    "#000000": "NEGRO",
}


@dataclass(slots=True)
class CacheEntry:
    path: Path
    mtime: float
    size: int
    partial_hash: str
    book: Book | None
    expert_index: dict[str, Any] | None
    error: str | None


class ACBRepository:
    def __init__(self, acb_dir: str | Path) -> None:
        self.acb_dir = Path(acb_dir)
        self.cache_dir = self.acb_dir.parent / ".cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, CacheEntry] = {}
        self._id_to_path: dict[str, Path] = {}
        self._usage_score: dict[str, int] = {}
        self._lock = RLock()

    def list_books(self, mode: str = "normal") -> tuple[list[dict[str, Any]], str | None]:
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
                item: dict[str, Any] = {
                    "id": book_id,
                    "filename": path.name,
                    "title": path.stem,
                    "format": file_format,
                    "color_count": len(entry.book.colors),
                    "colorspace": entry.book.colorspace_name,
                }
                if mode == "expert":
                    item["metadata"] = _infer_book_metadata(path.stem, entry.book)
                    if entry.expert_index:
                        item["duplicate_family_count"] = len(entry.expert_index.get("families", []))
                books.append(item)
            return books, None

    def get_book_details(self, book_id: str, mode: str = "normal") -> dict[str, Any]:
        with self._lock:
            path, book, entry = self._require_book(book_id)
            payload: dict[str, Any] = {
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
            if mode == "expert":
                payload["metadata"] = _infer_book_metadata(path.stem, book)
                payload["colors"] = list(entry.expert_index.get("colors", [])) if entry.expert_index else []
                payload["families"] = list(entry.expert_index.get("families", [])) if entry.expert_index else []
            return payload

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

    def search_book_text(
        self,
        book_id: str,
        query: str,
        offset: int = 0,
        limit: int = 100,
        mode: str = "normal",
    ) -> dict[str, Any]:
        with self._lock:
            path, book, entry = self._require_book(book_id)
            q = query.strip().lower()
            source = (
                list(entry.expert_index.get("colors", []))
                if mode == "expert" and entry.expert_index
                else [
                    {"name": color.name, "code": color.code or None, "hex": color.hex}
                    for color in book.colors
                ]
            )
            filtered = []
            for item in source:
                name = str(item.get("name", ""))
                code = str(item.get("code") or "")
                if not q or q in name.lower() or q in code.lower() or q in str(item.get("hex", "")).lower():
                    filtered.append(
                        {
                            "name": name,
                            "code": item.get("code") or None,
                            "hex": item.get("hex"),
                        }
                    )
            total = len(filtered)
            start = max(0, int(offset))
            end = start + max(1, int(limit))
            return {
                "book_id": book_id,
                "book_title": path.stem,
                "query": query,
                "offset": start,
                "limit": max(1, int(limit)),
                "total": total,
                "items": filtered[start:end],
            }

    def search_by_hex(
        self,
        query: str,
        book_id: str | None = None,
        limit: int = 200,
        mode: str = "normal",
        achromatic_threshold_white: float = 2.0,
        achromatic_threshold_black: float = 2.0,
        achromatic_enabled: bool = True,
    ) -> dict[str, Any]:
        with self._lock:
            error = self._refresh_id_map()
            if error:
                raise FileNotFoundError(error)

            target_rgb = parse_color_input(query)
            normalized_hex = rgb_to_hex(target_rgb)
            target_lab = rgb_to_lab_d50(target_rgb)

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
            probable = None
            if achromatic_enabled:
                probable = _detect_probable_achromatic(
                    target_rgb=target_rgb,
                    threshold_white=achromatic_threshold_white,
                    threshold_black=achromatic_threshold_black,
                    scope_book_id=scope_book_id,
                    scope_book_title=scoped_books[0][1].stem if len(scoped_books) == 1 else "Coincidencia fija",
                    scope_filename=scoped_books[0][1].name if len(scoped_books) == 1 else "",
                )
            if probable is not None and mode == "expert":
                return {
                    "query": normalized_hex,
                    "scope": scope_label,
                    "scope_book_id": scope_book_id,
                    "exact_count": 0,
                    "exact_matches": [],
                    "nearest": [probable | {"distance": 0, "delta_e": probable.get("delta_e", 0.0)}],
                    "top5": [probable | {"reason": "Color cercano a extremo acromatico configurado."}],
                    "input_rgb": target_rgb,
                    "probable_achromatic": True,
                }

            exact_matches: list[dict[str, Any]] = []
            nearest: list[tuple[float, float, float, dict[str, Any]]] = []

            for scoped_id, path in scoped_books:
                entry = self._load_cached(scoped_id, path)
                if entry.error or entry.book is None:
                    continue

                colors = (
                    list(entry.expert_index.get("colors", []))
                    if mode == "expert" and entry.expert_index
                    else [
                        {
                            "name": color.name,
                            "code": color.code or None,
                            "hex": color.hex,
                            "rgb": _hex_to_rgb(color.hex),
                            "lab_d50": rgb_to_lab_d50(_hex_to_rgb(color.hex)),
                        }
                        for color in entry.book.colors
                    ]
                )
                for color in colors:
                    item = {
                        "book_id": scoped_id,
                        "book_title": path.stem,
                        "filename": path.name,
                        "name": color.get("name"),
                        "code": color.get("code") or None,
                        "hex": color.get("hex"),
                    }

                    if str(color.get("hex", "")).upper() == normalized_hex:
                        exact_matches.append(item)

                    rgb = tuple(color.get("rgb") or _hex_to_rgb(str(color.get("hex"))))
                    lab = tuple(color.get("lab_d50") or rgb_to_lab_d50(rgb))
                    distance = float(_rgb_distance(target_rgb, rgb))
                    delta_e = float(delta_e_ciede2000(target_lab, lab))
                    rarity_penalty = 0.2 if not color.get("code") else 0.0
                    usage_bonus = min(2.0, float(self._usage_score.get(_usage_key(scoped_id, item["name"]), 0)) * 0.05)
                    score = delta_e + rarity_penalty - usage_bonus
                    nearest.append((score, delta_e, distance, item))

            nearest.sort(key=lambda row: row[0])
            nearest_items = []
            for score, delta_e, distance, item in nearest[:limit]:
                item_with_meta = item | {"distance": int(round(distance))}
                if mode == "expert":
                    item_with_meta |= {
                        "delta_e": round(delta_e, 3),
                        "reliability": reliability_label(delta_e),
                        "score": round(score, 3),
                    }
                nearest_items.append(item_with_meta)

            top5 = nearest_items[:5]
            if top5:
                for top in top5:
                    if mode == "expert":
                        top["reason"] = _build_reason(top)
                        self._usage_score[_usage_key(str(top.get("book_id")), str(top.get("name")))] = (
                            self._usage_score.get(_usage_key(str(top.get("book_id")), str(top.get("name"))), 0) + 1
                        )

            payload = {
                "query": normalized_hex,
                "scope": scope_label,
                "scope_book_id": scope_book_id,
                "exact_count": len(exact_matches),
                "exact_matches": exact_matches[:limit],
                "nearest": nearest_items,
            }
            if mode == "expert":
                payload["input_rgb"] = target_rgb
                payload["top5"] = top5
            return payload

    def nearest_in_book(
        self,
        target_rgb: tuple[int, int, int],
        book_id: str,
        mode: str = "normal",
        achromatic_threshold_white: float = 2.0,
        achromatic_threshold_black: float = 2.0,
        achromatic_enabled: bool = True,
    ) -> dict[str, Any]:
        with self._lock:
            path, book, entry = self._require_book(book_id)
            forced_match = _forced_achromatic_item_from_rgb(
                target_rgb=target_rgb,
                scope_book_id=book_id,
                scope_book_title=path.stem,
                scope_filename=path.name,
            )
            if forced_match is not None:
                return forced_match | {"distance": 0}
            if achromatic_enabled and mode == "expert":
                probable = _detect_probable_achromatic(
                    target_rgb=target_rgb,
                    threshold_white=achromatic_threshold_white,
                    threshold_black=achromatic_threshold_black,
                    scope_book_id=book_id,
                    scope_book_title=path.stem,
                    scope_filename=path.name,
                )
                if probable is not None:
                    return probable | {"distance": 0}

            target_lab = rgb_to_lab_d50(target_rgb)
            nearest: tuple[float, int, Any] | None = None
            colors = (
                list(entry.expert_index.get("colors", []))
                if mode == "expert" and entry.expert_index
                else [
                    {
                        "name": color.name,
                        "code": color.code or None,
                        "hex": color.hex,
                        "rgb": _hex_to_rgb(color.hex),
                        "lab_d50": rgb_to_lab_d50(_hex_to_rgb(color.hex)),
                    }
                    for color in book.colors
                ]
            )
            for color in colors:
                rgb = tuple(color.get("rgb") or _hex_to_rgb(str(color.get("hex"))))
                distance = _rgb_distance(target_rgb, rgb)
                delta_e = delta_e_ciede2000(target_lab, tuple(color.get("lab_d50") or rgb_to_lab_d50(rgb)))
                score = float(delta_e)
                if nearest is None or score < nearest[0]:
                    nearest = (
                        score,
                        distance,
                        {
                            "name": color.get("name"),
                            "code": color.get("code"),
                            "hex": color.get("hex"),
                            "delta_e": round(float(delta_e), 3),
                            "reliability": reliability_label(float(delta_e)),
                        },
                    )

            if nearest is None:
                raise RuntimeError(f"No hay colores disponibles en la paleta: {book_id}")

            score, distance, color = nearest
            payload = {
                "book_id": book_id,
                "book_title": path.stem,
                "filename": path.name,
                "name": color["name"],
                "code": color["code"] or None,
                "hex": color["hex"],
                "distance": distance,
            }
            if mode == "expert":
                payload["delta_e"] = color["delta_e"]
                payload["reliability"] = color["reliability"]
                payload["score"] = round(score, 3)
            return payload

    def _require_book(self, book_id: str) -> tuple[Path, Book, CacheEntry]:
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
        return path, entry.book, entry

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
        stat = path.stat()
        mtime = stat.st_mtime
        size = int(stat.st_size)
        partial_hash = _compute_partial_hash(path)
        cached = self._cache.get(book_id)
        if (
            cached
            and cached.path == path
            and cached.mtime == mtime
            and cached.size == size
            and cached.partial_hash == partial_hash
        ):
            return cached

        try:
            suffix = path.suffix.lower()
            if suffix == ".acb":
                book = parse_acb(path)
            elif suffix == ".ase":
                book = parse_ase(path)
            else:
                raise ValueError(f"Extension de archivo no soportada: {path.suffix}")

            expert_index = self._load_or_build_expert_index(
                book_id=book_id,
                path=path,
                mtime=mtime,
                size=size,
                partial_hash=partial_hash,
                book=book,
            )
            entry = CacheEntry(
                path=path,
                mtime=mtime,
                size=size,
                partial_hash=partial_hash,
                book=book,
                expert_index=expert_index,
                error=None,
            )
        except Exception as exc:
            entry = CacheEntry(
                path=path,
                mtime=mtime,
                size=size,
                partial_hash=partial_hash,
                book=None,
                expert_index=None,
                error=str(exc),
            )

        self._cache[book_id] = entry
        return entry

    def _load_or_build_expert_index(
        self,
        book_id: str,
        path: Path,
        mtime: float,
        size: int,
        partial_hash: str,
        book: Book,
    ) -> dict[str, Any]:
        cache_path = self.cache_dir / f"{book_id}.json"
        if cache_path.exists():
            try:
                raw = json.loads(cache_path.read_text(encoding="utf-8"))
                if (
                    float(raw.get("mtime", -1.0)) == float(mtime)
                    and int(raw.get("size", -1)) == size
                    and str(raw.get("partial_hash", "")) == partial_hash
                ):
                    return raw
            except Exception:
                pass

        colors = []
        for color in book.colors or []:
            rgb = _hex_to_rgb(color.hex)
            lab_d50 = rgb_to_lab_d50(rgb)
            lab_d65 = rgb_to_lab_d65(rgb)
            cmyk = rgb_to_cmyk(rgb)
            colors.append(
                {
                    "name": color.name,
                    "code": color.code or None,
                    "hex": color.hex,
                    "rgb": [int(rgb[0]), int(rgb[1]), int(rgb[2])],
                    "lab_d50": [round(lab_d50[0], 4), round(lab_d50[1], 4), round(lab_d50[2], 4)],
                    "lab_d65": [round(lab_d65[0], 4), round(lab_d65[1], 4), round(lab_d65[2], 4)],
                    "cmyk_approx": [
                        round(cmyk[0] * 100.0, 2),
                        round(cmyk[1] * 100.0, 2),
                        round(cmyk[2] * 100.0, 2),
                        round(cmyk[3] * 100.0, 2),
                    ],
                }
            )
        families = _build_duplicate_families(colors)
        payload = {
            "book_id": book_id,
            "filename": path.name,
            "mtime": mtime,
            "size": size,
            "partial_hash": partial_hash,
            "metadata": _infer_book_metadata(path.stem, book),
            "colors": colors,
            "families": families,
        }
        cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return payload

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


def _compute_partial_hash(path: Path, sample_size: int = 65536) -> str:
    with path.open("rb") as handle:
        chunk = handle.read(sample_size)
    return hashlib.sha1(chunk).hexdigest()


def _build_duplicate_families(colors: list[dict[str, Any]], threshold_delta_e: float = 1.5) -> list[dict[str, Any]]:
    families: list[dict[str, Any]] = []
    assigned: set[int] = set()
    for index, color in enumerate(colors):
        if index in assigned:
            continue
        base_lab = tuple(color.get("lab_d50") or rgb_to_lab_d50(color.get("rgb", [0, 0, 0])))
        members = [index]
        for other_index in range(index + 1, len(colors)):
            if other_index in assigned:
                continue
            other = colors[other_index]
            other_lab = tuple(other.get("lab_d50") or rgb_to_lab_d50(other.get("rgb", [0, 0, 0])))
            if delta_e_ciede2000(base_lab, other_lab) <= threshold_delta_e:
                members.append(other_index)
                assigned.add(other_index)
        if len(members) > 1:
            families.append(
                {
                    "base_name": color.get("name"),
                    "size": len(members),
                    "members": [
                        {
                            "name": colors[item_index].get("name"),
                            "hex": colors[item_index].get("hex"),
                            "code": colors[item_index].get("code"),
                        }
                        for item_index in members
                    ],
                }
            )
    return families


def _infer_book_metadata(title: str, book: Book) -> dict[str, Any]:
    low = title.lower()
    book_type = "unknown"
    if "coated" in low:
        book_type = "coated"
    elif "uncoated" in low:
        book_type = "uncoated"

    gamut = "standard"
    if "extended gamut" in low:
        gamut = "extended-gamut"
    elif "metallic" in low:
        gamut = "metallic"
    elif "pastels" in low or "neons" in low:
        gamut = "pastel-neon"

    return {
        "version": int(getattr(book, "version", 0) or 0),
        "book_id": int(getattr(book, "book_id", 0) or 0),
        "type": book_type,
        "gamut": gamut,
        "notes": getattr(book, "description", "") or "",
    }


def _usage_key(book_id: str, name: str) -> str:
    return f"{book_id}::{name}"


def _build_reason(item: dict[str, Any]) -> str:
    delta = float(item.get("delta_e", 999.0))
    reliability = str(item.get("reliability", "Dudoso"))
    score = float(item.get("score", delta))
    return f"ΔE={delta:.2f}, fiabilidad={reliability}, score={score:.2f}"


def _detect_probable_achromatic(
    target_rgb: tuple[int, int, int],
    threshold_white: float,
    threshold_black: float,
    scope_book_id: str | None,
    scope_book_title: str,
    scope_filename: str,
) -> dict[str, Any] | None:
    lab_target = rgb_to_lab_d50(target_rgb)
    lab_white = rgb_to_lab_d50((255, 255, 255))
    lab_black = rgb_to_lab_d50((0, 0, 0))
    de_white = delta_e_ciede2000(lab_target, lab_white)
    de_black = delta_e_ciede2000(lab_target, lab_black)

    if de_white <= threshold_white:
        return {
            "book_id": scope_book_id,
            "book_title": scope_book_title,
            "filename": scope_filename,
            "name": "BLANCO probable",
            "code": None,
            "hex": "#FFFFFF",
            "delta_e": round(de_white, 3),
            "reliability": reliability_label(de_white),
        }
    if de_black <= threshold_black:
        return {
            "book_id": scope_book_id,
            "book_title": scope_book_title,
            "filename": scope_filename,
            "name": "NEGRO probable",
            "code": None,
            "hex": "#000000",
            "delta_e": round(de_black, 3),
            "reliability": reliability_label(de_black),
        }
    return None
