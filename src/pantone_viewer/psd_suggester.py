from __future__ import annotations

import base64
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
    noise: float = 35.0,
    include_hidden: bool = False,
    include_overlay: bool = True,
    ignore_background: bool = False,
) -> dict[str, Any]:
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_IMAGE_EXTENSIONS:
        raise RuntimeError(f"Formato de archivo no soportado: {extension or '(sin extension)'}")

    if extension == ".psd":
        layers = _extract_layers_from_psd(
            psd_bytes=file_bytes,
            include_hidden=include_hidden,
            include_overlay=include_overlay,
        )
    else:
        layers = _extract_layers_from_raster(file_bytes, filename)

    layer_payload: list[dict[str, Any]] = []
    summary_by_pantone: dict[str, dict[str, Any]] = {}

    for layer in layers:
        color_clusters = _extract_dominant_clusters(
            image=layer["image"],
            noise=noise,
            ignore_background=ignore_background,
        )
        if not color_clusters:
            continue

        layer_colors: list[dict[str, Any]] = []
        for cluster in color_clusters:
            rgb = cluster["rgb"]
            detected_hex = rgb_to_hex(rgb)
            nearest = repository.nearest_in_book(rgb, palette_id)
            layer_colors.append(
                {
                    "detected_hex": detected_hex,
                    "pantone": nearest,
                    "weight": cluster["weight"],
                }
            )

            summary_key = _pantone_key(nearest)
            existing_summary = summary_by_pantone.get(summary_key)
            if existing_summary is None:
                summary_by_pantone[summary_key] = {
                    "pantone": nearest,
                    "occurrences": 1,
                    "layers": [layer["name"]],
                }
            else:
                existing_summary["occurrences"] += 1
                if layer["name"] not in existing_summary["layers"]:
                    existing_summary["layers"].append(layer["name"])

        layer_colors.sort(key=lambda item: float(item["weight"]), reverse=True)
        for item in layer_colors:
            item.pop("weight", None)

        layer_payload.append(
            {
                "layer_name": layer["name"],
                "visible": bool(layer.get("visible", True)),
                "preview_data_url": layer.get("preview_data_url"),
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
        "options": {
            "noise": _normalize_noise(noise),
            "include_hidden": include_hidden,
            "include_overlay": include_overlay,
            "ignore_background": ignore_background,
        },
    }


def _extract_layers_from_psd(
    psd_bytes: bytes, include_hidden: bool, include_overlay: bool
) -> list[dict[str, Any]]:
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
        is_visible = bool(layer.is_visible())
        if not include_hidden and not is_visible:
            continue

        rendered = None
        try:
            if include_overlay:
                rendered = layer.composite(force=True)
            else:
                rendered = layer.topil()
        except Exception:
            try:
                rendered = layer.composite(force=True)
            except Exception:
                rendered = None
        if rendered is None:
            continue

        image = rendered.convert("RGBA")
        index += 1
        layers.append(
            {
                "name": layer.name or f"Capa {index}",
                "visible": is_visible,
                "image": image,
                "preview_data_url": _to_preview_data_url(image),
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
            "preview_data_url": _to_preview_data_url(image),
        }
    ]


def _extract_dominant_clusters(
    image: Image.Image, noise: float, ignore_background: bool
) -> list[dict[str, Any]]:
    max_colors, similar_rgb_distance2, min_cluster_ratio, quant_shift = _noise_profile(noise)

    rgba = image.convert("RGBA")
    width, height = rgba.size
    pixel_count = width * height

    max_pixels = 220_000
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

            if quant_shift > 0:
                key = (r >> quant_shift, g >> quant_shift, b >> quant_shift)
            else:
                key = (r, g, b)

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
            if _rgb_distance2(existing["rgb"], rgb) <= similar_rgb_distance2:
                existing["weight"] += cluster["weight"]
                merged_into_existing = True
                break
        if not merged_into_existing:
            merged.append({"weight": cluster["weight"], "rgb": rgb})

    merged.sort(key=lambda item: float(item["weight"]), reverse=True)
    total_weight = sum(float(item["weight"]) for item in merged)
    if total_weight <= 0:
        return []

    with_ratio = []
    for item in merged:
        ratio = float(item["weight"]) / total_weight
        with_ratio.append({"weight": item["weight"], "rgb": item["rgb"], "ratio": ratio})

    if ignore_background:
        with_ratio = _remove_background_cluster(with_ratio)
        if not with_ratio:
            return []

    filtered = [item for item in with_ratio if float(item["ratio"]) >= min_cluster_ratio]
    if not filtered and with_ratio:
        filtered = [with_ratio[0]]

    return [
        {"weight": item["weight"], "rgb": item["rgb"]}
        for item in filtered[:max_colors]
    ]


def _extract_dominant_rgbs(image: Image.Image, max_colors: int = 8) -> list[tuple[int, int, int]]:
    clusters = _extract_dominant_clusters(
        image=image,
        noise=100.0,
        ignore_background=False,
    )
    return [item["rgb"] for item in clusters[:max_colors]]


def _remove_background_cluster(clusters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not clusters:
        return clusters

    top = clusters[0]
    if top["ratio"] >= 0.95:
        return clusters[1:]

    if len(clusters) > 1 and top["ratio"] >= 0.82:
        return clusters[1:]

    return clusters


def _noise_profile(noise: float) -> tuple[int, int, float, int]:
    n = _normalize_noise(noise) / 100.0

    # n bajo: mas global; n alto: mas detalle
    max_colors = int(round(1 + (n * 23)))  # 1..24
    similar_distance = int(round(40 - (n * 38)))  # 40..2
    min_cluster_ratio = 0.22 - (n * 0.215)  # 0.22..0.005
    quant_shift = int(round(4 - (n * 4)))  # 4..0

    distance2 = similar_distance * similar_distance * 3
    return max_colors, distance2, max(0.003, float(min_cluster_ratio)), max(0, quant_shift)


def _to_preview_data_url(image: Image.Image, size: int = 84) -> str:
    thumb = image.copy()
    thumb.thumbnail((size, size), Image.Resampling.BILINEAR)
    buffer = BytesIO()
    thumb.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _normalize_noise(noise: float) -> float:
    try:
        value = float(noise)
    except Exception:
        value = 35.0
    return max(0.0, min(100.0, value))


def _pantone_key(pantone: dict[str, Any]) -> str:
    return f"{pantone.get('book_id','')}::{pantone.get('name','')}::{pantone.get('hex','')}"


def _rgb_distance2(left: tuple[int, int, int], right: tuple[int, int, int]) -> int:
    return (
        (left[0] - right[0]) * (left[0] - right[0])
        + (left[1] - right[1]) * (left[1] - right[1])
        + (left[2] - right[2]) * (left[2] - right[2])
    )
