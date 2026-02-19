from PIL import Image

from pantone_viewer.psd_suggester import (
    _extract_dominant_rgbs,
    _noise_profile,
    suggest_from_file_bytes,
)


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


def test_extract_dominant_rgbs_merges_similar_tones() -> None:
    image = Image.new("RGBA", (6, 1))
    image.putdata(
        [
            (220, 30, 30, 255),
            (222, 28, 31, 255),
            (218, 32, 29, 255),
            (221, 29, 30, 255),
            (219, 31, 32, 255),
            (220, 30, 29, 255),
        ]
    )

    colors = _extract_dominant_rgbs(image, max_colors=6)
    assert len(colors) == 1
    r, g, b = colors[0]
    assert r > 180 and g < 80 and b < 80


class _FakeRepository:
    def nearest_in_book(self, target_rgb, book_id):
        r, g, b = target_rgb
        if r > g:
            return {
                "book_id": book_id,
                "book_title": "Demo",
                "filename": "demo.acb",
                "name": "PANTONE RED",
                "code": "R",
                "hex": "#FF0000",
                "distance": 0,
            }
        return {
            "book_id": book_id,
            "book_title": "Demo",
            "filename": "demo.acb",
            "name": "PANTONE GREEN",
            "code": "G",
            "hex": "#00FF00",
            "distance": 0,
        }


def test_summary_groups_by_pantone_not_detected_hex() -> None:
    image = Image.new("RGBA", (4, 2))
    image.putdata(
        [
            (220, 30, 30, 255),
            (222, 28, 31, 255),
            (0, 240, 0, 255),
            (0, 230, 0, 255),
            (220, 30, 30, 255),
            (222, 28, 31, 255),
            (0, 240, 0, 255),
            (0, 230, 0, 255),
        ]
    )
    from io import BytesIO

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    payload = suggest_from_file_bytes(
        file_bytes=buffer.getvalue(),
        filename="sample.png",
        repository=_FakeRepository(),
        palette_id="demo",
    )

    names = {item["pantone"]["name"] for item in payload["summary_colors"]}
    assert names == {"PANTONE RED", "PANTONE GREEN"}


def test_noise_100_can_keep_two_close_variants() -> None:
    image = Image.new("RGBA", (8, 1))
    image.putdata(
        [
            (210, 30, 30, 255),
            (212, 32, 32, 255),
            (208, 28, 30, 255),
            (240, 40, 40, 255),
            (242, 42, 41, 255),
            (238, 39, 39, 255),
            (0, 0, 0, 0),
            (0, 0, 0, 0),
        ]
    )
    from io import BytesIO

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    payload = suggest_from_file_bytes(
        file_bytes=buffer.getvalue(),
        filename="sample.png",
        repository=_FakeRepository(),
        palette_id="demo",
        noise=100.0,
    )
    assert len(payload["layers"]) == 1
    assert len(payload["layers"][0]["colors"]) >= 2


def test_ignore_background_removes_full_layer_color() -> None:
    image = Image.new("RGBA", (10, 10), (255, 255, 255, 255))
    for x in range(3):
        for y in range(3):
            image.putpixel((x, y), (220, 30, 30, 255))

    from io import BytesIO

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    payload = suggest_from_file_bytes(
        file_bytes=buffer.getvalue(),
        filename="sample.png",
        repository=_FakeRepository(),
        palette_id="demo",
        ignore_background=True,
        noise=10.0,
    )

    assert len(payload["layers"]) == 1
    first_layer = payload["layers"][0]
    assert first_layer["colors"]
    assert all(color["detected_hex"] != "#FFFFFF" for color in first_layer["colors"])


def test_ignore_background_does_not_remove_when_border_not_uniform() -> None:
    image = Image.new("RGBA", (10, 10), (255, 255, 255, 255))
    for x in range(10):
        image.putpixel((x, 0), (0, 255, 0, 255))
        image.putpixel((x, 9), (0, 255, 0, 255))
    for y in range(10):
        image.putpixel((0, y), (0, 255, 0, 255))
        image.putpixel((9, y), (0, 255, 0, 255))
    for x in range(4, 7):
        for y in range(4, 7):
            image.putpixel((x, y), (220, 30, 30, 255))

    from io import BytesIO

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    payload = suggest_from_file_bytes(
        file_bytes=buffer.getvalue(),
        filename="sample.png",
        repository=_FakeRepository(),
        palette_id="demo",
        ignore_background=True,
        noise=10.0,
    )

    assert len(payload["layers"]) == 1
    first_layer = payload["layers"][0]
    assert any(color["detected_hex"] == "#FFFFFF" for color in first_layer["colors"])


def test_max_colors_caps_detected_suggestions() -> None:
    image = Image.new("RGBA", (6, 2))
    image.putdata(
        [
            (230, 20, 20, 255),
            (230, 20, 20, 255),
            (20, 230, 20, 255),
            (20, 230, 20, 255),
            (20, 20, 230, 255),
            (20, 20, 230, 255),
            (230, 20, 20, 255),
            (230, 20, 20, 255),
            (20, 230, 20, 255),
            (20, 230, 20, 255),
            (20, 20, 230, 255),
            (20, 20, 230, 255),
        ]
    )
    from io import BytesIO

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    payload = suggest_from_file_bytes(
        file_bytes=buffer.getvalue(),
        filename="sample.png",
        repository=_FakeRepository(),
        palette_id="demo",
        noise=100.0,
        max_colors=1,
    )

    assert len(payload["layers"]) == 1
    assert len(payload["layers"][0]["colors"]) == 1
    assert payload["options"]["max_colors"] == 1
    assert len(payload["summary_colors"]) == 1


def test_noise_profile_high_end_is_smoother() -> None:
    _, distance2_97, ratio_97, _ = _noise_profile(97.0)
    _, distance2_100, ratio_100, _ = _noise_profile(100.0)
    assert abs(distance2_97 - distance2_100) < 25.0
    assert abs(ratio_97 - ratio_100) < 0.02
