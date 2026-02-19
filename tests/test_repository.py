from pathlib import Path

from pantone_viewer.repository import (
    ACBRepository,
    _forced_achromatic_item_from_hex,
    _forced_achromatic_item_from_rgb,
    _normalize_hex,
)


def test_default_palette_prefers_solid_coated() -> None:
    mapping = {
        "x": Path("PANTONE CMYK Coated.acb"),
        "y": Path("PANTONE Solid Coated-V4.acb"),
        "z": Path("something.ase"),
    }
    assert ACBRepository._pick_default_palette_id(mapping) == "y"


def test_normalize_hex_short_form() -> None:
    assert _normalize_hex("#abc") == "#AABBCC"


def test_forced_white_result_is_blanco() -> None:
    item = _forced_achromatic_item_from_hex(
        normalized_hex="#FFFFFF",
        scope_book_id="demo",
        scope_book_title="Demo",
        scope_filename="demo.acb",
    )
    assert item is not None
    assert item["name"] == "BLANCO"
    assert item["hex"] == "#FFFFFF"


def test_forced_black_result_is_negro() -> None:
    item = _forced_achromatic_item_from_rgb(
        target_rgb=(0, 0, 0),
        scope_book_id="demo",
        scope_book_title="Demo",
        scope_filename="demo.acb",
    )
    assert item is not None
    assert item["name"] == "NEGRO"
    assert item["hex"] == "#000000"
