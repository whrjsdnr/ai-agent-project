"""Generate a deterministic multi-size ICO from our original geometric A mark.

The design matches desktop_app/assets/ai-agent.svg. No external artwork/library.
"""

import struct
from pathlib import Path


def inside(x: float, y: float, points: tuple) -> bool:
    hit = False
    previous = points[-1]
    for current in points:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            hit = not hit
        previous = current
    return hit


def icon_bytes() -> bytes:
    images = []
    sizes = (16, 32, 48, 64, 128, 256)
    shape = (
        (48, 194),
        (108, 58),
        (148, 58),
        (208, 194),
        (166, 194),
        (155, 165),
        (101, 165),
        (90, 194),
    )
    hole = ((113, 131), (143, 131), (128, 91))
    for size in sizes:
        pixels = bytearray()
        for y in reversed(range(size)):
            for x in range(size):
                px, py = (x + 0.5) * 256 / size, (y + 0.5) * 256 / size
                white = inside(px, py, shape) and not inside(px, py, hole)
                pixels.extend((255, 255, 255, 255) if white else (171, 93, 39, 255))
        mask = bytes(((size + 31) // 32) * 4 * size)
        header = struct.pack(
            "<IIIHHIIIIII", 40, size, size * 2, 1, 32, 0, len(pixels), 0, 0, 0, 0
        )
        images.append(header + pixels + mask)
    offset = 6 + 16 * len(sizes)
    directory = bytearray(struct.pack("<HHH", 0, 1, len(sizes)))
    for size, data in zip(sizes, images, strict=True):
        directory.extend(
            struct.pack(
                "<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset
            )
        )
        offset += len(data)
    return bytes(directory) + b"".join(images)


if __name__ == "__main__":
    target = Path(__file__).resolve().parents[2] / "build" / "assets" / "ai-agent.ico"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(icon_bytes())
