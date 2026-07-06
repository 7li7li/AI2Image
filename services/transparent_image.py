from __future__ import annotations

import math
from array import array
from io import BytesIO

from PIL import Image

GREEN_KEY_COLOR = "#00FF00"
MAGENTA_KEY_COLOR = "#FF00FF"

_KEY_COLOR_RGB = {
    GREEN_KEY_COLOR: (0, 255, 0),
    MAGENTA_KEY_COLOR: (255, 0, 255),
}

_TRANSPARENT_PROMPT_TEMPLATE = "\n".join(
    [
        "[背景指令]",
        "背景色选择规则：如果主体包含绿色系（绿、青绿、黄绿、草绿等）颜色，使用纯洋红色(#FF00FF)背景；否则一律使用纯绿色(#00FF00)背景。",
        "背景要求：整张画布仅由所选纯色填充，无任何渐变、纹理、阴影、光照变化、地面或环境元素。",
        "主体要求：单主体、完整呈现、轮廓清晰锐利。主体与背景之间保持干净的边缘分离，不要有颜色溢出或混合。",
        "禁止：主体本身、描边、光晕、投影或反射中不能出现所选背景色。",
    ]
)


def build_transparent_prompt(prompt: str) -> str:
    return f"{prompt.strip()}\n\n{_TRANSPARENT_PROMPT_TEMPLATE}"


def remove_keyed_background(image_data: bytes, key_color: str | None = None) -> bytes:
    with Image.open(BytesIO(image_data)) as source:
        image = source.convert("RGBA")

    width, height = image.size
    pixels = bytearray(image.tobytes())
    if _has_transparent_border(pixels, width, height):
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    effective_key_color = key_color or detect_key_color_from_pixels(pixels, width, height)
    remove_keyed_background_from_pixels(pixels, width, height, effective_key_color)

    output = Image.frombytes("RGBA", (width, height), bytes(pixels))
    buffer = BytesIO()
    output.save(buffer, format="PNG")
    return buffer.getvalue()


def detect_key_color_from_pixels(data: bytearray | bytes, width: int, height: int) -> str:
    border_indices: list[int] = []
    for x in range(width):
        border_indices.append(x)
        border_indices.append((height - 1) * width + x)
    for y in range(1, height - 1):
        border_indices.append(y * width)
        border_indices.append(y * width + width - 1)

    green_score = 0
    magenta_score = 0
    green_rgb = _KEY_COLOR_RGB[GREEN_KEY_COLOR]
    magenta_rgb = _KEY_COLOR_RGB[MAGENTA_KEY_COLOR]

    for index in border_indices:
        offset = index * 4
        red = data[offset]
        green = data[offset + 1]
        blue = data[offset + 2]
        green_dist = math.sqrt((red - green_rgb[0]) ** 2 + (green - green_rgb[1]) ** 2 + (blue - green_rgb[2]) ** 2)
        magenta_dist = math.sqrt(
            (red - magenta_rgb[0]) ** 2 + (green - magenta_rgb[1]) ** 2 + (blue - magenta_rgb[2]) ** 2
        )
        if green_dist < 100:
            green_score += 1
        if magenta_dist < 100:
            magenta_score += 1

    return MAGENTA_KEY_COLOR if magenta_score > green_score else GREEN_KEY_COLOR


def remove_keyed_background_from_pixels(data: bytearray, width: int, height: int, key_color: str) -> bytearray:
    if len(data) < width * height * 4:
        raise ValueError("透明背景像素数据尺寸不匹配")
    key_rgb = _get_key_color_rgb(key_color)
    mask = _build_background_mask(data, width, height, key_rgb)
    _write_transparent_pixels(data, mask, width, height, key_rgb)
    return data


def _has_transparent_border(data: bytearray, width: int, height: int) -> bool:
    for x in range(width):
        if data[x * 4 + 3] < 255:
            return True
        if data[((height - 1) * width + x) * 4 + 3] < 255:
            return True
    for y in range(1, height - 1):
        if data[(y * width) * 4 + 3] < 255:
            return True
        if data[(y * width + width - 1) * 4 + 3] < 255:
            return True
    return False


def _build_background_mask(data: bytearray, width: int, height: int, key_rgb: tuple[int, int, int]) -> bytearray:
    mask = _build_connected_background_mask(data, width, height, key_rgb)
    _add_interior_key_color_islands(data, width, height, key_rgb, mask)
    return mask


def _build_connected_background_mask(data: bytearray, width: int, height: int, key_rgb: tuple[int, int, int]) -> bytearray:
    pixel_count = width * height
    mask = bytearray(pixel_count)
    visited = bytearray(pixel_count)
    queue = array("I", [0]) * pixel_count
    queue_start = 0
    queue_end = 0

    def enqueue(index: int) -> None:
        nonlocal queue_end
        if visited[index]:
            return
        visited[index] = 1
        if _get_background_confidence(data, index, key_rgb) < 0.18:
            return
        mask[index] = 1
        queue[queue_end] = index
        queue_end += 1

    for x in range(width):
        enqueue(x)
        enqueue((height - 1) * width + x)
    for y in range(1, height - 1):
        enqueue(y * width)
        enqueue(y * width + width - 1)

    while queue_start < queue_end:
        index = queue[queue_start]
        queue_start += 1
        x = index % width
        y = index // width
        if x > 0:
            enqueue(index - 1)
        if x < width - 1:
            enqueue(index + 1)
        if y > 0:
            enqueue(index - width)
        if y < height - 1:
            enqueue(index + width)

    return mask


def _add_interior_key_color_islands(
    data: bytearray,
    width: int,
    height: int,
    key_rgb: tuple[int, int, int],
    mask: bytearray,
) -> None:
    pixel_count = width * height
    visited = bytearray(pixel_count)
    queue = array("I", [0]) * pixel_count
    component = array("I", [0]) * pixel_count

    for seed in range(pixel_count):
        if mask[seed] or visited[seed]:
            continue
        if _get_background_confidence(data, seed, key_rgb) < 0.68:
            continue

        queue_start = 0
        queue_end = 0
        component_length = 0
        confidence_sum = 0.0
        strict_count = 0
        strong_count = 0

        visited[seed] = 1
        queue[queue_end] = seed
        queue_end += 1

        def enqueue_neighbor(neighbor_index: int) -> None:
            nonlocal queue_end
            if neighbor_index < 0 or mask[neighbor_index] or visited[neighbor_index]:
                return
            if _get_background_confidence(data, neighbor_index, key_rgb) < 0.24:
                return
            visited[neighbor_index] = 1
            queue[queue_end] = neighbor_index
            queue_end += 1

        while queue_start < queue_end:
            index = queue[queue_start]
            queue_start += 1
            confidence = _get_background_confidence(data, index, key_rgb)
            component[component_length] = index
            component_length += 1
            confidence_sum += confidence
            if confidence >= 0.68:
                strict_count += 1
            if confidence >= 0.86:
                strong_count += 1

            x = index % width
            y = index // width
            enqueue_neighbor(index - 1 if x > 0 else -1)
            enqueue_neighbor(index + 1 if x < width - 1 else -1)
            enqueue_neighbor(index - width if y > 0 else -1)
            enqueue_neighbor(index + width if y < height - 1 else -1)

        average_confidence = confidence_sum / component_length
        strict_ratio = strict_count / component_length
        strong_ratio = strong_count / component_length
        should_remove = (
            average_confidence >= 0.42
            or strict_ratio >= 0.18
            or strong_ratio >= 0.05
            or (component_length <= 3 and average_confidence >= 0.34)
        )

        if should_remove:
            for i in range(component_length):
                mask[component[i]] = 1


def _write_transparent_pixels(
    data: bytearray,
    mask: bytearray,
    width: int,
    height: int,
    key_rgb: tuple[int, int, int],
) -> None:
    distance_to_background = _compute_distance_to_background(mask, width, height, 4)
    pixel_count = width * height

    for index in range(pixel_count):
        offset = index * 4
        red = data[offset]
        green = data[offset + 1]
        blue = data[offset + 2]
        confidence = _get_background_confidence(data, index, key_rgb)
        alpha = 255

        if mask[index]:
            alpha = 0
        else:
            distance = distance_to_background[index]
            if distance > 0:
                transparency = _get_edge_transparency(red, green, blue, confidence, distance, key_rgb)
                if transparency > 0:
                    alpha = round(255 * (1 - transparency))
                alpha = max(alpha, 48 if distance == 1 else 128 if distance == 2 else 196)
            else:
                isolated_spill = _get_key_channel_mix(red, green, blue, key_rgb)
                if confidence >= 0.46 and isolated_spill >= 0.45:
                    alpha = round(255 * (1 - isolated_spill * 0.75))
                    alpha = max(alpha, 96)

        cleaned = _remove_color_spill(red, green, blue, alpha, key_rgb, confidence, distance_to_background[index])
        data[offset] = cleaned[0]
        data[offset + 1] = cleaned[1]
        data[offset + 2] = cleaned[2]
        data[offset + 3] = alpha


def _compute_distance_to_background(mask: bytearray, width: int, height: int, max_distance: int) -> bytearray:
    pixel_count = width * height
    distance = bytearray(pixel_count)
    frontier: list[int] = []

    for index in range(pixel_count):
        if mask[index]:
            continue
        x = index % width
        y = index // width
        touches_background = (
            (x > 0 and mask[index - 1])
            or (x < width - 1 and mask[index + 1])
            or (y > 0 and mask[index - width])
            or (y < height - 1 and mask[index + width])
        )
        if touches_background:
            distance[index] = 1
            frontier.append(index)

    for current_distance in range(1, max_distance):
        next_frontier: list[int] = []
        for index in frontier:
            x = index % width
            y = index // width
            _add_distance_neighbor(distance, mask, next_frontier, index - 1 if x > 0 else -1, current_distance)
            _add_distance_neighbor(distance, mask, next_frontier, index + 1 if x < width - 1 else -1, current_distance)
            _add_distance_neighbor(distance, mask, next_frontier, index - width if y > 0 else -1, current_distance)
            _add_distance_neighbor(distance, mask, next_frontier, index + width if y < height - 1 else -1, current_distance)
        frontier = next_frontier
        if not frontier:
            break

    return distance


def _add_distance_neighbor(
    distance: bytearray,
    mask: bytearray,
    next_frontier: list[int],
    neighbor_index: int,
    current_distance: int,
) -> None:
    if neighbor_index < 0 or mask[neighbor_index] or distance[neighbor_index] != 0:
        return
    distance[neighbor_index] = current_distance + 1
    next_frontier.append(neighbor_index)


def _get_background_confidence(data: bytearray, index: int, key_rgb: tuple[int, int, int]) -> float:
    offset = index * 4
    color_distance = math.sqrt(
        (data[offset] - key_rgb[0]) ** 2
        + (data[offset + 1] - key_rgb[1]) ** 2
        + (data[offset + 2] - key_rgb[2]) ** 2
    )
    return _clamp01((150 - color_distance) / 150)


def _get_edge_transparency(
    red: int,
    green: int,
    blue: int,
    confidence: float,
    distance: int,
    key_rgb: tuple[int, int, int],
) -> float:
    edge_strength = 1 if distance <= 1 else 0.75 if distance == 2 else 0.45 if distance == 3 else 0.25
    distance_estimate = _clamp01(((confidence - 0.08) / 0.84) * edge_strength)
    channel_estimate = _get_key_channel_mix(red, green, blue, key_rgb) * edge_strength
    return _clamp01(max(distance_estimate, channel_estimate))


def _get_key_channel_mix(red: int, green: int, blue: int, key_rgb: tuple[int, int, int]) -> float:
    if key_rgb[1] == 255:
        return _clamp01((green - min(red, blue)) / 255)
    return _clamp01((min(red, blue) - green * 0.65) / 255)


def _remove_color_spill(
    red: int,
    green: int,
    blue: int,
    alpha: int,
    key_rgb: tuple[int, int, int],
    confidence: float,
    distance_to_background: int,
) -> tuple[int, int, int]:
    if alpha == 0:
        return red, green, blue

    edge_strength = (
        0.35
        if distance_to_background <= 0 and confidence >= 0.46
        else 0
        if distance_to_background <= 0
        else 0.55
        if distance_to_background == 1
        else 0.32
        if distance_to_background == 2
        else 0.16
    )
    spill_mix = _get_key_channel_mix(red, green, blue, key_rgb) * edge_strength
    background_mix = _clamp01(max((255 - alpha) / 255, ((confidence - 0.1) / 0.9) * edge_strength, spill_mix))
    if background_mix <= 0:
        return red, green, blue

    foreground_mix = max(0.08, 1 - background_mix)
    return (
        _clamp_byte((red - key_rgb[0] * background_mix) / foreground_mix),
        _clamp_byte((green - key_rgb[1] * background_mix) / foreground_mix),
        _clamp_byte((blue - key_rgb[2] * background_mix) / foreground_mix),
    )


def _get_key_color_rgb(key_color: str) -> tuple[int, int, int]:
    rgb = _KEY_COLOR_RGB.get(key_color.upper())
    if rgb is None:
        raise ValueError("透明背景键色不支持")
    return rgb


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _clamp_byte(value: float) -> int:
    return max(0, min(255, round(value)))
