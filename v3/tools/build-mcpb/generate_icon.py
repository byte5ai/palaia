#!/usr/bin/env python3
"""Generates ``icon.png`` — a minimal, dependency-free placeholder icon.

No image library is available in every environment this repo builds in
(no Pillow pin exists for v3, and adding one just for one 512x512 PNG
would be a heavier dependency than the icon is worth), so this writes a
valid PNG by hand: a filled circle on a transparent background, using only
``zlib`` and ``struct`` from the standard library. Re-run this script (`uv
run python generate_icon.py` from this directory) if the icon ever needs
to change; the output is checked in so the CI packaging job does not need
to run this or need any extra tooling.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

SIZE = 512
# A calm indigo, distinct enough to recognize at extension-list thumbnail
# size; not a claimed brand color, just a legible placeholder.
FILL = (74, 58, 173, 255)
TRANSPARENT = (0, 0, 0, 0)


def _chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))


def build_png() -> bytes:
    center = SIZE / 2
    radius = SIZE * 0.42
    rows = []
    for y in range(SIZE):
        row = bytearray()
        for x in range(SIZE):
            dx, dy = x - center + 0.5, y - center + 0.5
            inside = (dx * dx + dy * dy) <= radius * radius
            row.extend(FILL if inside else TRANSPARENT)
        rows.append(bytes([0]) + bytes(row))  # filter type 0 (none) per scanline
    raw = b"".join(rows)

    ihdr = struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0)  # 8-bit RGBA, no interlace
    idat = zlib.compress(raw, 9)

    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", idat)
        + _chunk(b"IEND", b"")
    )


def main() -> None:
    out = Path(__file__).parent / "icon.png"
    out.write_bytes(build_png())
    print(f"wrote {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
