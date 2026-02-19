from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

from .color_convert import rgb_to_hex
from .repository import ACBRepository

SUPPORTED_IMAGE_EXTENSIONS = {".psd", ".png", ".jpg", ".jpeg"}

SIMILAR_RGB_DISTANCE2 = 14 * 14 * 3
MIN_CLUSTER_RATIO = 0.03


def suggest_from_file_bytes(
    file_bytes: bytes,
    filename: str,
    repository: ACBRepository,
    palette_id: str,
) -> dict[str, Any]:
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_IMAGE_EXTENSIONS:
        raise RuntimeError(f"Formato de archivo no soportado: {extension or '(sin extension)'}")

    if extension == ".psd":
        layers = _extract_layers_from_psd(file_bytes)
    else:
        layers = _extract_layers_from_raster(file_bytes, filename)

    layer_payload: list[dict[str, Any]] = []
    summary_by_pantone: dict[str, dict[str, Any]] = {}

    for layer in layers:
        color_clusters = _extract_dominant_clusters(layer["image"], max_colors=10)
        if not color_clusters:
            continue

        layer_color_map: dict[str, dict[str, Any]] = {}
        for cluster in color_clusters:
            rgb = cluster["rgb"]
            detected_hex = rgb_to_hex(rgb)
            nearest = repository.nearest_in_book(rgb, palette_id)
            pantone_key = _pantone_key(nearest)

            existing_layer_color = layer_color_map.get(pantone_key)
            if existing_layer_color is None:
                layer_color_map[pantone_key] = {
                    "detected_hex": detected_hex,
                    "pantone": nearest,
                    "weight": cluster["weight"],
                }
            else:
                previous_weight = float(existing_layer_color["weight"])
                existing_layer_color["weight"] += cluster["weight"]
                if float(cluster["weight"]) > previous_weight:
                    existing_layer_color["detected_hex"] = detected_hex
                    existing_layer_color["pantone"] = nearest

        layer_colors = sorted(
            layer_color_map.values(),
            key=lambda item: float(item["weight"]),
            reverse=True,
        )
        for item in layer_colors:
            item.pop("weight", None)

            pantone = item["pantone"]
            summary_key = _pantone_key(pantone)
            existing_summary = summary_by_pantone.get(summary_key)
            if existing_summary is None:
                summary_by_pantone[summary_key] = {
                    "pantone": pantone,
                    "occurrences": 1,
                    "layers": [layer["name"]],
                }
            else:
                existing_summary["occurrences"] += 1
                if layer["name"] not in existing_summary["layers"]:
                    existing_summary["layers"].append(layer["name"])

        layer_payload.append(
            {
                "layer_name": layer["name"],
                "visible": bool(layer.get("visible", True)),
                "colors": layer_colors,
            }
        )

    summary_colors = sorted(
        summary_by_pantone.values(),
        key=lambda item: (-int(item["occurrences"]), str(item["pantone"]["name"])),
    )
    return {
        "layer_count": len(layer_payload),
        "layers": layer_payload,
        "summary_colors": summary_colors,
    }


def _extract_layers_from_psd(psd_bytes: bytes) -> list[dict[str, Any]]:
    try:
        from psd_tools import PSDImage
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("psd-tools es requerido para importar PSD") from exc

    psd = PSDImage.open(BytesIO(psd_bytes))
    layers: list[dict[str, Any]] = []
    index = 0
    for layer in psd.descendants():
        if layer.is_group():
            continue

        try:
            rendered = layer.composite()
        except Exception:
            continue
        if rendered is None:
            continue

        index += 1
        layers.append(
            {
                "name": layer.name or f"Capa {index}",
                "visible": bool(layer.is_visible()),
                "image": rendered.convert("RGBA"),
            }
        )
    return layers


def _extract_layers_from_raster(image_bytes: bytes, filename: str) -> list[dict[str, Any]]:
    image = Image.open(BytesIO(image_bytes)).convert("RGBA")
    return [
        {
            "name": f"Imagen {Path(filename).name}",
            "visible": True,
            "image": image,
        }
    ]


def _extract_dominant_clusters(image: Image.Image, max_colors: int = 8) -> list[dict[str, Any]]:
    rgba = image.convert("RGBA")
    width, height = rgba.size
    pixel_count = width * height

    max_pixels = 160_000
    if pixel_count > max_pixels:
        scale = (max_pixels / float(pixel_count)) ** 0.5
        width = max(1, int(width * scale))
        height = max(1, int(height * scale))
        rgba = rgba.resize((width, height), Image.Resampling.BILINEAR)

    bins: dict[tuple[int, int, int], list[float]] = {}
    for y in range(height):
        for x in range(width):
            r, g, b, a = rgba.getpixel((x, y))
            if a < 16:
                continue

            key = (r >> 3, g >> 3, b >> 3)
            weight = a / 255.0

            bucket = bins.get(key)
            if bucket is None:
                bins[key] = [weight, r * weight, g * weight, b * weight]
            else:
                bucket[0] += weight
                bucket[1] += r * weight
                bucket[2] += g * weight
                bucket[3] += b * weight

    if not bins:
        return []

    raw_clusters: list[dict[str, Any]] = []
    for values in bins.values():
        weight = values[0]
        if weight <= 0:
            continue
        raw_clusters.append(
            {
                "weight": weight,
                "rgb": (
                    int(round(values[1] / weight)),
                    int(round(values[2] / weight)),
                    int(round(values[3] / weight)),
                ),
            }
        )

    raw_clusters.sort(key=lambda item: float(item["weight"]), reverse=True)
    merged: list[dict[str, Any]] = []
    for cluster in raw_clusters:
        rgb = cluster["rgb"]
        merged_into_existing = False
        for existing in merged:
            if _rgb_distance2(existing["rgb"], rgb) <= SIMILAR_RGB_DISTANCE2:
                existing["weight"] += cluster["weight"]
                merged_into_existing = True
                break
        if not merged_into_existing:
            merged.append({"weight": cluster["weight"], "rgb": rgb})

    merged.sort(key=lambda item: float(item["weight"]), reverse=True)
    total_weight = sum(float(item["weight"]) for item in merged)
    if total_weight <= 0:
        return []

    filtered = [
        item
        for item in merged
        if (float(item["weight"]) / total_weight) >= MIN_CLUSTER_RATIO
    ]
    if not filtered and merged:
        filtered = [merged[0]]

    return filtered[:max_colors]


def _extract_dominant_rgbs(image: Image.Image, max_colors: int = 8) -> list[tuple[int, int, int]]:
    return [item["rgb"] for item in _extract_dominant_clusters(image, max_colors=max_colors)]


def _pantone_key(pantone: dict[str, Any]) -> str:
    return f"{pantone.get('book_id','')}::{pantone.get('name','')}::{pantone.get('hex','')}"


def _rgb_distance2(left: tuple[int, int, int], right: tuple[int, int, int]) -> int:
    return (
        (left[0] - right[0]) * (left[0] - right[0])
        + (left[1] - right[1]) * (left[1] - right[1])
        + (left[2] - right[2]) * (left[2] - right[2])
    )
