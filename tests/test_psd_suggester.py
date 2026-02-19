from PIL import Image

from pantone_viewer.psd_suggester import _extract_dominant_rgbs


def test_extract_dominant_rgbs_returns_multiple_colors() -> None:
    image = Image.new("RGBA", (4, 2))
    pixels = [
        (255, 0, 0, 255),
        (255, 0, 0, 255),
        (0, 255, 0, 255),
        (0, 255, 0, 255),
        (0, 0, 255, 255),
        (0, 0, 255, 255),
        (0, 0, 0, 0),
        (0, 0, 0, 0),
    ]
    image.putdata(pixels)

    colors = _extract_dominant_rgbs(image, max_colors=3)
    assert len(colors) == 3
    assert any(r > 200 and g < 50 and b < 50 for r, g, b in colors)
    assert any(g > 200 and r < 50 and b < 50 for r, g, b in colors)
    assert any(b > 200 and r < 50 and g < 50 for r, g, b in colors)

