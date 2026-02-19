from pantone_viewer.color_convert import cmyk_bytes_to_rgb, cmyk_to_rgb, rgb_to_hex


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
