from pathlib import Path

from pantone_viewer.repository import ACBRepository, _normalize_hex


def test_default_palette_prefers_solid_coated() -> None:
    mapping = {
        "x": Path("PANTONE CMYK Coated.acb"),
        "y": Path("PANTONE Solid Coated-V4.acb"),
        "z": Path("something.ase"),
    }
    assert ACBRepository._pick_default_palette_id(mapping) == "y"


def test_normalize_hex_short_form() -> None:
    assert _normalize_hex("#abc") == "#AABBCC"

