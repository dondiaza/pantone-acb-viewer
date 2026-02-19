from PIL import Image

from pantone_viewer.psd_suggester import _average_visible_rgb


def test_average_visible_rgb_ignores_transparent_pixels() -> None:
    image = Image.new("RGBA", (2, 1))
    image.putdata([(255, 0, 0, 255), (0, 0, 255, 0)])
    assert _average_visible_rgb(image) == (255, 0, 0)

