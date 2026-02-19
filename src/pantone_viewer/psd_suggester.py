from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

from .color_convert import delta_e_ciede2000, reliability_label, rgb_to_hex, rgb_to_lab_d50
from .repository import ACBRepository

SUPPORTED_IMAGE_EXTENSIONS = {".psd", ".png", ".jpg", ".jpeg"}


def suggest_from_file_bytes(
    file_bytes: bytes,
    filename: str,
    repository: ACBRepository,
    palette_id: str,
    mode: str = "normal",
    noise: float = 35.0,
    max_colors: int = 0,
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
            max_colors=max_colors,
        )
        if not color_clusters:
            continue

        layer_colors: list[dict[str, Any]] = []
        for cluster in color_clusters:
            rgb = cluster["rgb"]
            detected_hex = rgb_to_hex(rgb)
            try:
                nearest = repository.nearest_in_book(rgb, palette_id, mode=mode)
            except TypeError:
                nearest = repository.nearest_in_book(rgb, palette_id)
            if mode == "expert":
                detected_lab = rgb_to_lab_d50(rgb)
                pantone_lab = rgb_to_lab_d50(
                    (
                        int(nearest["hex"][1:3], 16),
                        int(nearest["hex"][3:5], 16),
                        int(nearest["hex"][5:7], 16),
                    )
                )
                delta_e = float(delta_e_ciede2000(detected_lab, pantone_lab))
                reliability = reliability_label(delta_e)
            else:
                delta_e = None
                reliability = None
            layer_colors.append(
                {
                    "detected_hex": detected_hex,
                    "pantone": nearest,
                    "weight": cluster["weight"],
                    "delta_e": round(delta_e, 3) if delta_e is not None else None,
                    "reliability": reliability,
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
                "layer_state": {
                    "visible": bool(layer.get("visible", True)),
                    "opacity_zero": bool(layer.get("opacity_zero", False)),
                    "clipped": bool(layer.get("clipped", False)),
                },
            }
        )

    summary_colors = sorted(
        summary_by_pantone.values(),
        key=lambda item: (-int(item["occurrences"]), str(item["pantone"]["name"])),
    )
    normalized_max_colors = _normalize_max_colors(max_colors)
    if normalized_max_colors > 0:
        summary_colors = summary_colors[:normalized_max_colors]

    if mode == "expert":
        _apply_weighted_summary(summary_colors, layer_payload)

    return {
        "layer_count": len(layer_payload),
        "layers": layer_payload,
        "summary_colors": summary_colors,
        "options": {
            "mode": mode,
            "noise": _normalize_noise(noise),
            "max_colors": normalized_max_colors,
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

        rendered: Image.Image | None = None
        if include_overlay:
            try:
                rendered = layer.composite(force=True)
            except Exception:
                rendered = None
            if rendered is None:
                try:
                    rendered = layer.topil()
                except Exception:
                    rendered = None
        else:
            try:
                rendered = layer.topil()
            except Exception:
                try:
                    rendered = layer.composite(force=True)
                except Exception:
                    rendered = None

        image = rendered.convert("RGBA") if rendered is not None else None

        if include_overlay:
            overlay = _extract_color_overlay_rgba(layer)
            if overlay is not None:
                if image is None:
                    image = overlay
                else:
                    image = _apply_overlay_color(image, overlay)

        if image is None:
            continue

        index += 1
        opacity_zero = False
        clipped = bool(getattr(layer, "clipping", False))
        try:
            opacity_zero = int(getattr(layer, "opacity", 255)) == 0
        except Exception:
            opacity_zero = False
        layers.append(
            {
                "name": layer.name or f"Capa {index}",
                "visible": is_visible,
                "opacity_zero": opacity_zero,
                "clipped": clipped,
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
    image: Image.Image, noise: float, ignore_background: bool, max_colors: int = 0
) -> list[dict[str, Any]]:
    auto_max_colors, similar_rgb_distance2, min_cluster_ratio, quant_shift = _noise_profile(noise)
    max_colors_value = _normalize_max_colors(max_colors)
    effective_max_colors = max_colors_value if max_colors_value > 0 else auto_max_colors

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
    border_bins: dict[tuple[int, int, int], list[float]] = {}
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

            if x == 0 or y == 0 or x == (width - 1) or y == (height - 1):
                border = border_bins.get(key)
                if border is None:
                    border_bins[key] = [weight, r * weight, g * weight, b * weight]
                else:
                    border[0] += weight
                    border[1] += r * weight
                    border[2] += g * weight
                    border[3] += b * weight

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

    border_rgb, border_ratio = _dominant_border_color(border_bins)

    if ignore_background:
        with_ratio = _remove_background_cluster(
            with_ratio,
            border_rgb=border_rgb,
            border_ratio=border_ratio,
            similar_rgb_distance2=similar_rgb_distance2,
        )
        if not with_ratio:
            return []

    filtered = [item for item in with_ratio if float(item["ratio"]) >= min_cluster_ratio]
    if not filtered and with_ratio:
        filtered = [with_ratio[0]]

    return [
        {"weight": item["weight"], "rgb": item["rgb"]}
        for item in filtered[:effective_max_colors]
    ]


def _extract_dominant_rgbs(image: Image.Image, max_colors: int = 8) -> list[tuple[int, int, int]]:
    clusters = _extract_dominant_clusters(
        image=image,
        noise=35.0,
        ignore_background=False,
        max_colors=max_colors,
    )
    return [item["rgb"] for item in clusters[:max_colors]]


def _remove_background_cluster(
    clusters: list[dict[str, Any]],
    border_rgb: tuple[int, int, int] | None,
    border_ratio: float,
    similar_rgb_distance2: float,
) -> list[dict[str, Any]]:
    if not clusters:
        return clusters

    if border_rgb is None:
        return clusters

    top = clusters[0]
    if top["ratio"] < 0.90:
        return clusters
    if border_ratio < 0.80:
        return clusters

    tolerance = max(120.0, float(similar_rgb_distance2) * 2.0)
    if _rgb_distance2(top["rgb"], border_rgb) > tolerance:
        return clusters

    if len(clusters) > 1:
        return clusters[1:]

    # Capa totalmente solida. Si se ignora fondo, no quedan colores.
    return []


def _noise_profile(noise: float) -> tuple[int, float, float, int]:
    n = _normalize_noise(noise) / 100.0
    detail = n**1.15

    # n bajo: mas global; n alto: mas detalle, con transicion suave en tramo alto.
    max_colors = int(round(2 + (detail * 22)))  # 2..24
    similar_distance = 22.0 - (detail * 18.0)  # 22..4
    min_cluster_ratio = 0.24 - (detail * 0.232)  # 0.24..0.008
    quant_shift = int(round((1.0 - detail) * 3.0))  # 3..0

    distance2 = (similar_distance * similar_distance) * 3.0
    return max_colors, distance2, max(0.003, float(min_cluster_ratio)), max(0, quant_shift)


def _to_preview_data_url(image: Image.Image, size: int = 84) -> str:
    thumb = image.copy()
    thumb.thumbnail((size, size), Image.Resampling.BILINEAR)
    buffer = BytesIO()
    thumb.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _dominant_border_color(
    border_bins: dict[tuple[int, int, int], list[float]]
) -> tuple[tuple[int, int, int] | None, float]:
    if not border_bins:
        return None, 0.0

    total = 0.0
    dominant = None
    dominant_weight = 0.0
    for values in border_bins.values():
        weight = float(values[0])
        if weight <= 0:
            continue
        total += weight
        if weight > dominant_weight:
            dominant_weight = weight
            dominant = values

    if dominant is None or total <= 0:
        return None, 0.0

    w = float(dominant[0])
    rgb = (
        int(round(float(dominant[1]) / w)),
        int(round(float(dominant[2]) / w)),
        int(round(float(dominant[3]) / w)),
    )
    return rgb, (w / total)


def _extract_color_overlay_rgba(layer) -> Image.Image | None:
    try:
        effects = layer.effects
        candidates = list(effects.find("ColorOverlay", enabled=True))
    except Exception:
        return None
    if not candidates:
        return None

    effect = candidates[0]
    descriptor = getattr(effect, "color", None)
    if descriptor is None:
        return None

    rgb = _descriptor_to_rgb(descriptor)
    if rgb is None:
        return None

    opacity = getattr(effect, "opacity", 100)
    try:
        opacity_value = float(getattr(opacity, "value", opacity))
    except Exception:
        opacity_value = 100.0
    alpha = int(round(max(0.0, min(100.0, opacity_value)) * 2.55))

    width = max(1, int(getattr(layer, "width", 1) or 1))
    height = max(1, int(getattr(layer, "height", 1) or 1))
    return Image.new("RGBA", (width, height), (rgb[0], rgb[1], rgb[2], alpha))


def _descriptor_to_rgb(descriptor) -> tuple[int, int, int] | None:
    try:
        from psd_tools.terminology import Key
    except Exception:
        Key = None

    def _pick(keys: list[Any]) -> float | None:
        for key in keys:
            if key is None:
                continue
            try:
                value = descriptor.get(key)
            except Exception:
                value = None
            if value is None:
                continue
            raw = getattr(value, "value", value)
            try:
                return float(raw)
            except Exception:
                continue
        return None

    red = _pick([getattr(Key, "Red", None), b"Rd  ", "Red", getattr(Key, "RedFloat", None), b"RdF "])
    green = _pick([getattr(Key, "Green", None), b"Grn ", "Green", getattr(Key, "GreenFloat", None), b"GrnF"])
    blue = _pick([getattr(Key, "Blue", None), b"Bl  ", "Blue", getattr(Key, "BlueFloat", None), b"BlF "])

    if red is None or green is None or blue is None:
        return None

    if red <= 1.0 and green <= 1.0 and blue <= 1.0:
        red *= 255.0
        green *= 255.0
        blue *= 255.0

    return (
        max(0, min(255, int(round(red)))),
        max(0, min(255, int(round(green)))),
        max(0, min(255, int(round(blue)))),
    )


def _apply_overlay_color(base_image: Image.Image, overlay_image: Image.Image) -> Image.Image:
    base = base_image.convert("RGBA")
    overlay = overlay_image.convert("RGBA")
    if overlay.size != base.size:
        overlay = overlay.resize(base.size, Image.Resampling.BILINEAR)

    r, g, b, overlay_alpha = overlay.getpixel((0, 0))
    alpha_mask = base.getchannel("A")

    if _alpha_is_empty(alpha_mask):
        return overlay

    factor = overlay_alpha / 255.0
    combined_alpha = alpha_mask.point(lambda p: int(round(p * factor)))

    colored = Image.new("RGBA", base.size, (r, g, b, 0))
    colored.putalpha(combined_alpha)
    return colored


def _alpha_is_empty(alpha_image: Image.Image) -> bool:
    bbox = alpha_image.getbbox()
    return bbox is None


def _normalize_noise(noise: float) -> float:
    try:
        value = float(noise)
    except Exception:
        value = 35.0
    return max(0.0, min(100.0, value))


def _normalize_max_colors(max_colors: int | float | None) -> int:
    try:
        value = int(float(max_colors))
    except Exception:
        value = 0
    return max(0, min(15, value))


def _pantone_key(pantone: dict[str, Any]) -> str:
    return f"{pantone.get('book_id','')}::{pantone.get('name','')}::{pantone.get('hex','')}"


def _rgb_distance2(left: tuple[int, int, int], right: tuple[int, int, int]) -> int:
    return (
        (left[0] - right[0]) * (left[0] - right[0])
        + (left[1] - right[1]) * (left[1] - right[1])
        + (left[2] - right[2]) * (left[2] - right[2])
    )


def _apply_weighted_summary(
    summary_colors: list[dict[str, Any]],
    layers: list[dict[str, Any]],
) -> None:
    if not summary_colors:
        return

    layer_weight_map: dict[str, float] = {}
    for layer in layers:
        name = str(layer.get("layer_name", ""))
        layer_state = layer.get("layer_state") or {}
        weight = 1.0
        if not bool(layer_state.get("visible", True)):
            weight *= 0.4
        if bool(layer_state.get("opacity_zero", False)):
            weight *= 0.2
        if bool(layer_state.get("clipped", False)):
            weight *= 0.7
        layer_weight_map[name] = weight

    for item in summary_colors:
        layers_list = item.get("layers", []) or []
        base_occurrences = float(item.get("occurrences", 0))
        weighted = 0.0
        for layer_name in layers_list:
            weighted += layer_weight_map.get(str(layer_name), 1.0)
        if weighted <= 0.0:
            weighted = base_occurrences
        item["weighted_score"] = round(weighted, 3)

    summary_colors.sort(
        key=lambda item: (
            -float(item.get("weighted_score", 0.0)),
            -int(item.get("occurrences", 0)),
            str(item.get("pantone", {}).get("name", "")),
        )
    )
