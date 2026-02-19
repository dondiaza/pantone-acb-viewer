from __future__ import annotations

from io import BytesIO
from typing import Any

from .color_convert import rgb_to_hex
from .repository import ACBRepository


def suggest_from_psd_bytes(
    psd_bytes: bytes, repository: ACBRepository, palette_id: str
) -> dict[str, Any]:
    try:
        from psd_tools import PSDImage
    except Exception as exc:  # pragma: no cover - import guard for runtime env
        raise RuntimeError("psd-tools is required for PSD import") from exc

    psd = PSDImage.open(BytesIO(psd_bytes))
    layer_infos: list[dict[str, Any]] = []

    for layer in psd.descendants():
        if layer.is_group():
            continue

        try:
            rendered = layer.composite()
        except Exception:
            continue
        if rendered is None:
            continue

        avg_rgb = _average_visible_rgb(rendered)
        if avg_rgb is None:
            continue

        pantone = repository.nearest_in_book(avg_rgb, palette_id)
        layer_infos.append(
            {
                "layer_name": layer.name or f"Layer {len(layer_infos) + 1}",
                "visible": bool(layer.is_visible()),
                "detected_hex": rgb_to_hex(avg_rgb),
                "pantone": pantone,
            }
        )

    return {
        "layer_count": len(layer_infos),
        "layers": layer_infos,
    }


def _average_visible_rgb(image) -> tuple[int, int, int] | None:
    rgba = image.convert("RGBA")
    width, height = rgba.size
    step = max(1, (width * height) // 40000)

    total_r = 0.0
    total_g = 0.0
    total_b = 0.0
    total_weight = 0.0

    index = 0
    for y in range(height):
        for x in range(width):
            if index % step == 0:
                r, g, b, a = rgba.getpixel((x, y))
                if a > 0:
                    weight = a / 255.0
                    total_r += r * weight
                    total_g += g * weight
                    total_b += b * weight
                    total_weight += weight
            index += 1

    if total_weight == 0:
        return None

    return (
        int(round(total_r / total_weight)),
        int(round(total_g / total_weight)),
        int(round(total_b / total_weight)),
    )
