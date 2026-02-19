from __future__ import annotations

from pathlib import Path

from .acb_parser import Book, ByteReader, ColorRecord
from .color_convert import cmyk_to_rgb, gray_to_rgb, lab_to_rgb, rgb_to_hex


class ASEParseError(ValueError):
    pass


def parse_ase(path: str | Path) -> Book:
    file_path = Path(path)
    data = file_path.read_bytes()
    book = parse_ase_bytes(data, source=str(file_path))
    book.filename = file_path.name
    return book


def parse_ase_bytes(data: bytes, source: str = "<memory>") -> Book:
    reader = ByteReader(data, source=source)
    signature = reader.read_bytes(4, "signature")
    if signature != b"ASEF":
        raise ASEParseError(f"{source}: invalid signature {signature!r}, expected b'ASEF'")

    major = reader.read_u16("version major")
    minor = reader.read_u16("version minor")
    block_count = reader.read_u32("block count")

    colors: list[ColorRecord] = []
    models_seen: set[str] = set()
    group_stack: list[str] = []

    for block_index in range(block_count):
        block_type = reader.read_u16(f"block {block_index} type")
        block_length = reader.read_u32(f"block {block_index} length")
        payload = reader.read_bytes(block_length, f"block {block_index} payload")
        block_reader = ByteReader(payload, source=f"{source} block {block_index}")

        if block_type == 0xC001:
            group_name = _read_ase_string(block_reader, "group name")
            if group_name:
                group_stack.append(group_name)
            continue

        if block_type == 0xC002:
            if group_stack:
                group_stack.pop()
            continue

        if block_type != 0x0001:
            continue

        color_name = _read_ase_string(block_reader, "color name")
        if not color_name:
            continue

        model_raw = block_reader.read_bytes(4, "color model")
        model = model_raw.decode("ascii", errors="replace")
        model_key = model.strip().upper()
        models_seen.add(model_key)

        rgb = _read_ase_rgb(block_reader, model_key, source, block_index)
        color_type = block_reader.read_u16("color type") if block_reader.remaining() >= 2 else 2
        code = _format_color_code(model_key, color_type)

        if group_stack:
            display_name = f"{color_name} [{group_stack[-1]}]"
        else:
            display_name = color_name

        colors.append(ColorRecord(name=display_name, code=code, hex=rgb_to_hex(rgb)))

    colorspace_name = "Mixed" if len(models_seen) > 1 else (next(iter(models_seen), "Unknown"))
    version = (major * 100) + minor
    return Book(
        version=version,
        title="",
        description=f"ASE {major}.{minor}",
        color_count=len(colors),
        colorspace_name=colorspace_name,
        colors=colors,
        format="ASE",
    )


def _read_ase_string(reader: ByteReader, context: str) -> str:
    length = reader.read_u16(f"{context} length")
    if length == 0:
        return ""
    raw = reader.read_bytes(length * 2, context)
    return raw.decode("utf-16-be", errors="replace").rstrip("\x00")


def _read_ase_rgb(
    block_reader: ByteReader, model_key: str, source: str, block_index: int
) -> tuple[int, int, int]:
    if model_key == "RGB":
        r = block_reader.read_f32("RGB r")
        g = block_reader.read_f32("RGB g")
        b = block_reader.read_f32("RGB b")
        return (
            max(0, min(255, int(round(r * 255.0)))),
            max(0, min(255, int(round(g * 255.0)))),
            max(0, min(255, int(round(b * 255.0)))),
        )

    if model_key == "CMYK":
        c = block_reader.read_f32("CMYK c")
        m = block_reader.read_f32("CMYK m")
        y = block_reader.read_f32("CMYK y")
        k = block_reader.read_f32("CMYK k")
        return cmyk_to_rgb(c, m, y, k)

    if model_key == "LAB":
        l_value = block_reader.read_f32("Lab l")
        a_value = block_reader.read_f32("Lab a")
        b_value = block_reader.read_f32("Lab b")
        return lab_to_rgb(l_value, a_value, b_value)

    if model_key == "GRAY":
        gray = block_reader.read_f32("Gray")
        return gray_to_rgb(gray)

    raise ASEParseError(
        f"{source}: unsupported ASE model '{model_key}' in block {block_index}"
    )


def _format_color_code(model_key: str, color_type: int) -> str:
    type_labels = {
        0: "global",
        1: "spot",
        2: "process",
    }
    type_name = type_labels.get(color_type, str(color_type))
    return f"{model_key}/{type_name}"
