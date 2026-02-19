from pantone_viewer.color_convert import (
    cmyk_bytes_to_rgb,
    cmyk_to_rgb,
    delta_e_ciede2000,
    parse_color_input,
    reliability_label,
    rgb_to_hex,
)


def test_rgb_to_hex_uppercase() -> None:
    assert rgb_to_hex((228, 0, 43)) == "#E4002B"


def test_cmyk_bytes_to_rgb_white() -> None:
    assert cmyk_bytes_to_rgb(255, 255, 255, 255) == (255, 255, 255)


def test_cmyk_bytes_to_rgb_black() -> None:
    assert cmyk_bytes_to_rgb(255, 255, 255, 0) == (0, 0, 0)


def test_cmyk_bytes_to_rgb_red() -> None:
    assert cmyk_bytes_to_rgb(255, 0, 0, 255) == (255, 0, 0)


def test_cmyk_float_to_rgb_red() -> None:
    assert cmyk_to_rgb(0.0, 1.0, 1.0, 0.0) == (255, 0, 0)


def test_parse_color_input_rgb() -> None:
    assert parse_color_input("rgb(255,0,128)") == (255, 0, 128)


def test_parse_color_input_hsl_red() -> None:
    assert parse_color_input("hsl(0,100%,50%)") == (255, 0, 0)


def test_parse_color_input_cmyk_red() -> None:
    assert parse_color_input("cmyk(0,100,100,0)") == (255, 0, 0)


def test_delta_e_zero_same_color() -> None:
    lab = (50.0, 10.0, -20.0)
    assert abs(delta_e_ciede2000(lab, lab)) < 1e-9


def test_reliability_label() -> None:
    assert reliability_label(0.5) == "Excelente"
    assert reliability_label(2.0) == "Bueno"
    assert reliability_label(4.0) == "Dudoso"
