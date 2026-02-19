from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .color_convert import cmyk_bytes_to_rgb, lab_bytes_to_rgb, rgb_to_hex

COLORSPACE_LABELS = {
    0: "RGB",
    2: "CMYK",
    7: "Lab",
}


class ACBParseError(ValueError):
    pass


@dataclass(slots=True)
class ColorRecord:
    name: str
    code: str
    hex: str


@dataclass(slots=True)
class Book:
    version: int
    book_id: int
    title: str
    prefix: str
    suffix: str
    description: str
    color_count: int
    page_size: int
    page_selector_offset: int
    colorspace: int
    colorspace_name: str
    colors: list[ColorRecord]
    filename: str = ""


class ByteReader:
    def __init__(self, data: bytes, source: str = "<memory>") -> None:
        self.data = data
        self.pos = 0
        self.source = source

    def remaining(self) -> int:
        return len(self.data) - self.pos

    def _ensure(self, size: int, context: str) -> None:
        if self.remaining() < size:
            raise ACBParseError(
                f"{self.source}: unexpected EOF while reading {context} at offset {self.pos}"
            )

    def read_bytes(self, size: int, context: str) -> bytes:
        self._ensure(size, context)
        chunk = self.data[self.pos : self.pos + size]
        self.pos += size
        return chunk

    def read_u16(self, context: str) -> int:
        return int.from_bytes(self.read_bytes(2, context), "big")

    def read_u32(self, context: str) -> int:
        return int.from_bytes(self.read_bytes(4, context), "big")

    def peek_u32(self, offset: int = 0) -> int | None:
        start = self.pos + offset
        end = start + 4
        if end > len(self.data):
            return None
        return int.from_bytes(self.data[start:end], "big")


def read_pascal_utf16be_string(reader: ByteReader, context: str = "string") -> str:
    length_chars = reader.read_u32(f"{context} length")
    if length_chars == 0:
        return ""

    raw = reader.read_bytes(length_chars * 2, context)
    value = raw.decode("utf-16-be", errors="replace")
    return value.rstrip("\x00")


def parse_acb(path: str | Path) -> Book:
    file_path = Path(path)
    data = file_path.read_bytes()
    book = parse_acb_bytes(data, source=str(file_path))
    book.filename = file_path.name
    return book


def parse_acb_bytes(data: bytes, source: str = "<memory>") -> Book:
    reader = ByteReader(data, source=source)
    signature = reader.read_bytes(4, "signature")
    if signature != b"8BCB":
        raise ACBParseError(f"{source}: invalid signature {signature!r}, expected b'8BCB'")

    version = reader.read_u16("version")
    book_id = reader.read_u16("book id")
    title = read_pascal_utf16be_string(reader, "title")
    prefix = read_pascal_utf16be_string(reader, "prefix")
    suffix = read_pascal_utf16be_string(reader, "suffix")
    description = read_pascal_utf16be_string(reader, "description")

    color_count = reader.read_u16("color count")
    page_size = reader.read_u16("page size")
    page_selector_offset = reader.read_u16("page selector offset")
    colorspace = reader.read_u16("colorspace/library identifier")
    colorspace_name = COLORSPACE_LABELS.get(colorspace, f"Unknown({colorspace})")

    colors: list[ColorRecord] = []
    for index in range(color_count):
        record_context = f"record {index + 1}/{color_count}"
        name = read_pascal_utf16be_string(reader, f"{record_context} name")
        if not name:
            continue

        code_raw = reader.read_bytes(6, f"{record_context} color code")
        code = code_raw.decode("latin-1", errors="replace").strip()

        if colorspace == 0:
            r, g, b = reader.read_bytes(3, f"{record_context} RGB components")
            rgb = (r, g, b)
        elif colorspace == 2:
            c, m, y, k = reader.read_bytes(4, f"{record_context} CMYK components")
            rgb = cmyk_bytes_to_rgb(c, m, y, k)
        elif colorspace == 7:
            l_byte, a_byte, b_byte = reader.read_bytes(3, f"{record_context} Lab components")
            rgb = lab_bytes_to_rgb(l_byte, a_byte, b_byte)
        else:
            raise ACBParseError(
                f"{source}: unsupported colorspace {colorspace} while reading {record_context}"
            )

        _consume_optional_spot_identifier(reader, color_count - index - 1)
        colors.append(ColorRecord(name=name, code=code, hex=rgb_to_hex(rgb)))

    return Book(
        version=version,
        book_id=book_id,
        title=title,
        prefix=prefix,
        suffix=suffix,
        description=description,
        color_count=color_count,
        page_size=page_size,
        page_selector_offset=page_selector_offset,
        colorspace=colorspace,
        colorspace_name=colorspace_name,
        colors=colors,
    )


def _consume_optional_spot_identifier(reader: ByteReader, remaining_records: int) -> None:
    if remaining_records <= 0:
        return

    if _looks_like_next_record(reader, offset=0):
        return

    if reader.remaining() >= 8 and _looks_like_next_record(reader, offset=8):
        reader.read_bytes(8, "optional spot/process identifier")


def _looks_like_next_record(reader: ByteReader, offset: int) -> bool:
    name_length = reader.peek_u32(offset=offset)
    if name_length is None:
        return False

    remaining_after_offset = reader.remaining() - offset
    if name_length == 0:
        return remaining_after_offset >= 4

    if name_length > 32768:
        return False

    required = 4 + (name_length * 2)
    return required <= remaining_after_offset

