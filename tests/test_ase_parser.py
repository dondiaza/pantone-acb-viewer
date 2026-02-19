import struct

from pantone_viewer.ase_parser import parse_ase_bytes


def _pack_u16(value: int) -> bytes:
    return value.to_bytes(2, "big")


def _pack_u32(value: int) -> bytes:
    return value.to_bytes(4, "big")


def _pack_ase_string(value: str) -> bytes:
    text = value + "\x00"
    return _pack_u16(len(text)) + text.encode("utf-16-be")


def test_parse_minimal_ase_rgb() -> None:
    payload = b"".join(
        [
            _pack_ase_string("PANTONE TEST"),
            b"RGB ",
            struct.pack(">f", 1.0),
            struct.pack(">f", 0.0),
            struct.pack(">f", 0.0),
            _pack_u16(2),
        ]
    )
    data = b"".join(
        [
            b"ASEF",
            _pack_u16(1),
            _pack_u16(0),
            _pack_u32(1),
            _pack_u16(0x0001),
            _pack_u32(len(payload)),
            payload,
        ]
    )

    book = parse_ase_bytes(data)
    assert len(book.colors) == 1
    assert book.colors[0].name == "PANTONE TEST"
    assert book.colors[0].hex == "#FF0000"
    assert book.colorspace_name == "RGB"

