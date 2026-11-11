"""Write a Kairo .icns (PNG chunks) without iconutil, so the Dock icon exists before codesign."""
import struct, zlib
from pathlib import Path

def _png(size):
    rows = []
    for y in range(size):
        row = bytearray()
        m = int(size * 0.12)
        for x in range(size):
            inside = m < x < size - m and m < y < size - m
            stem = size * 0.28 <= x <= size * 0.40 and size * 0.22 <= y <= size * 0.78
            dx = x - size * 0.38
            upper = dx > 0 and abs((size * 0.50 - y) - dx * 0.85) < size * 0.045 and y < size * 0.52 and x < size * 0.74
            lower = dx > 0 and abs((y - size * 0.50) - dx * 0.85) < size * 0.045 and y > size * 0.48 and x < size * 0.74
            green = inside and (stem or upper or lower)
            if green:
                row += bytes((50, 215, 75, 255))
            elif inside:
                row += bytes((0, 0, 0, 255))
            else:
                row += bytes((0, 0, 0, 0))
        rows.append(bytes(row))
    raw = b"".join(b"\x00" + r for r in rows)
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")

def write_icns(dest):
    # PNG-encoded icon types used by modern macOS.
    types = {16: b"icp4", 32: b"icp5", 64: b"icp6", 128: b"ic07", 256: b"ic08", 512: b"ic09", 1024: b"ic10"}
    parts = []
    for size, tag in types.items():
        data = _png(size)
        parts.append(tag + struct.pack(">I", 8 + len(data)) + data)
    body = b"".join(parts)
    blob = b"icns" + struct.pack(">I", 8 + len(body)) + body
    Path(dest).write_bytes(blob)
    return dest
