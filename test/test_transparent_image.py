from __future__ import annotations

import unittest
from io import BytesIO

from PIL import Image

from services.transparent_image import (
    GREEN_KEY_COLOR,
    MAGENTA_KEY_COLOR,
    build_transparent_prompt,
    detect_key_color_from_pixels,
    remove_keyed_background,
    remove_keyed_background_from_pixels,
)


class TransparentImageTest(unittest.TestCase):
    def test_build_transparent_prompt_mentions_key_colors(self) -> None:
        prompt = build_transparent_prompt("单主体贴纸素材")

        self.assertIn("单主体贴纸素材", prompt)
        self.assertIn("#00FF00", prompt)
        self.assertIn("#FF00FF", prompt)
        self.assertIn("纯色填充", prompt)

    def test_detect_key_color_from_border_pixels(self) -> None:
        green_pixels = _create_pixels(5, 5, (0, 255, 0, 255))
        magenta_pixels = _create_pixels(5, 5, (255, 0, 255, 255))

        self.assertEqual(detect_key_color_from_pixels(green_pixels, 5, 5), GREEN_KEY_COLOR)
        self.assertEqual(detect_key_color_from_pixels(magenta_pixels, 5, 5), MAGENTA_KEY_COLOR)

    def test_remove_keyed_background_from_pixels_keeps_foreground(self) -> None:
        pixels = _create_pixels(3, 3, (0, 255, 0, 255))
        _set_pixel(pixels, 1, 1, 3, (200, 20, 20, 255))

        remove_keyed_background_from_pixels(pixels, 3, 3, GREEN_KEY_COLOR)

        self.assertEqual(_get_pixel(pixels, 0, 0, 3)[3], 0)
        self.assertEqual(_get_pixel(pixels, 1, 1, 3)[3], 255)

    def test_remove_keyed_background_outputs_png_with_alpha(self) -> None:
        image = Image.new("RGBA", (3, 3), (0, 255, 0, 255))
        image.putpixel((1, 1), (200, 20, 20, 255))
        source = BytesIO()
        image.save(source, format="PNG")

        output_bytes = remove_keyed_background(source.getvalue())

        with Image.open(BytesIO(output_bytes)) as output:
            output = output.convert("RGBA")
            self.assertEqual(output.getpixel((0, 0))[3], 0)
            self.assertEqual(output.getpixel((1, 1))[3], 255)


def _create_pixels(width: int, height: int, rgba: tuple[int, int, int, int]) -> bytearray:
    pixels = bytearray(width * height * 4)
    for index in range(width * height):
        pixels[index * 4:index * 4 + 4] = bytes(rgba)
    return pixels


def _set_pixel(pixels: bytearray, x: int, y: int, width: int, rgba: tuple[int, int, int, int]) -> None:
    offset = (y * width + x) * 4
    pixels[offset:offset + 4] = bytes(rgba)


def _get_pixel(pixels: bytearray, x: int, y: int, width: int) -> tuple[int, int, int, int]:
    offset = (y * width + x) * 4
    return tuple(pixels[offset:offset + 4])  # type: ignore[return-value]


if __name__ == "__main__":
    unittest.main()
