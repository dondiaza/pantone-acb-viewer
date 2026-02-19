from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

from .color_convert import rgb_to_hex
from .repository import ACBRepository

SUPPORTED_IMAGE_EXTENSIONS = {".psd", ".png", ".jpg", ".jpeg"}


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
    summary: dict[str, dict[str, Any]] = {}

    for layer in layers:
        detected_rgbs = _extract_dominant_rgbs(layer["image"], max_colors=8)
        if not detected_rgbs:
            continue

        layer_colors: list[dict[str, Any]] = []
        for rgb in detected_rgbs:
            detected_hex = rgb_to_hex(rgb)
            nearest = repository.nearest_in_book(rgb, palette_id)
            item = {
                "detected_hex": detected_hex,
                "pantone": nearest,
            }
            layer_colors.append(item)

            existing = summary.get(detected_hex)
            if existing is None:
                summary[detected_hex] = {
                    "detected_hex": detected_hex,
                    "pantone": nearest,
                    "occurrences": 1,
                    "layers": [layer["name"]],
                }
            else:
                existing["occurrences"] += 1
                if layer["name"] not in existing["layers"]:
                    existing["layers"].append(layer["name"])

        layer_payload.append(
            {
                "layer_name": layer["name"],
                "visible": bool(layer.get("visible", True)),
                "colors": layer_colors,
            }
        )

    summary_colors = sorted(
        summary.values(),
        key=lambda item: (-int(item["occurrences"]), str(item["detected_hex"])),
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


def _extract_dominant_rgbs(image: Image.Image, max_colors: int = 8) -> list[tuple[int, int, int]]:
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

    ordered = sorted(bins.values(), key=lambda values: values[0], reverse=True)
    result: list[tuple[int, int, int]] = []
    for bucket in ordered[:max_colors]:
        total = bucket[0]
        if total <= 0:
            continue
        result.append(
            (
                int(round(bucket[1] / total)),
                int(round(bucket[2] / total)),
                int(round(bucket[3] / total)),
            )
        )
    return result

