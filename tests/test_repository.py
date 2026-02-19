from pathlib import Path

from pantone_viewer.repository import (
    ACBRepository,
    _build_duplicate_families,
    _forced_achromatic_item_from_hex,
    _forced_achromatic_item_from_rgb,
    _infer_book_metadata,
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


def test_duplicate_families_detected() -> None:
    families = _build_duplicate_families(
        [
            {"name": "A", "hex": "#FF0000", "code": "1", "rgb": [255, 0, 0], "lab_d50": [53.24, 80.09, 67.2]},
            {"name": "B", "hex": "#FE0001", "code": "2", "rgb": [254, 0, 1], "lab_d50": [53.1, 79.8, 66.9]},
            {"name": "C", "hex": "#00FF00", "code": "3", "rgb": [0, 255, 0], "lab_d50": [87.7, -86.2, 83.2]},
        ],
        threshold_delta_e=1.5,
    )
    assert families
    assert families[0]["size"] >= 2


def test_infer_book_metadata_coated() -> None:
    class _Book:
        version = 7
        book_id = 9
        description = "Demo"

    metadata = _infer_book_metadata("PANTONE Solid Coated-V4", _Book())
    assert metadata["type"] == "coated"
    assert metadata["version"] == 7
