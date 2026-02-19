from pantone_viewer.acb_parser import ByteReader, parse_acb_bytes, read_pascal_utf16be_string


def _pack_u16(value: int) -> bytes:
    return value.to_bytes(2, "big")


def _pack_u32(value: int) -> bytes:
    return value.to_bytes(4, "big")


def _pack_pascal_utf16be(text: str) -> bytes:
    return _pack_u32(len(text)) + text.encode("utf-16-be")


def test_read_pascal_utf16be_string() -> None:
    data = _pack_u32(5) + "Hello".encode("utf-16-be")
    reader = ByteReader(data)
    assert read_pascal_utf16be_string(reader) == "Hello"


def test_parser_ignores_dummy_records() -> None:
    data = b"".join(
        [
            b"8BCB",
            _pack_u16(1),  # version
            _pack_u16(42),  # id
            _pack_pascal_utf16be("Test Book"),
            _pack_pascal_utf16be(""),
            _pack_pascal_utf16be(""),
            _pack_pascal_utf16be(""),
            _pack_u16(2),  # color count (one dummy + one color)
            _pack_u16(1),  # page size
            _pack_u16(0),  # page selector offset
            _pack_u16(0),  # colorspace RGB
            _pack_u32(0),  # dummy record (empty name)
            _pack_pascal_utf16be("PANTONE 186 C"),
            b"C0186 ",
            bytes([0xE4, 0x00, 0x2B]),
        ]
    )

    book = parse_acb_bytes(data)
    assert len(book.colors) == 1
    assert book.colors[0].name == "PANTONE 186 C"
    assert book.colors[0].hex == "#E4002B"
    assert book.colors[0].code == "C0186"

