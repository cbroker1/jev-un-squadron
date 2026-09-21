"""Measure the level's ground surface from capture screenshots, keyed by scroll position.

Terrain is not in the object table, but the level scrolls deterministically and
WRAM 0x007B holds the scroll position in pixels (screen x + scroll is constant for
stationary ground objects). For each captured frame this reads the top of the solid
region at the bottom of each column, converts it to level coordinates, and keeps the
median across frames so moving sprites drop out and only terrain remains.

Offline measurement only: no emulator, no API, no controller writes.
"""
import argparse
import json
import statistics
import struct
import zlib
from pathlib import Path

from brain.observations import captures

SCROLL = 0x7B
SKY_ROWS = range(40, 224)


def read_png(path):
    """Minimal PNG reader for the emulator's own screenshots (8-bit RGB/RGBA)."""
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    width = height = depth = colour = None
    idat = bytearray()
    offset = 8
    while offset < len(data):
        length, kind = struct.unpack(">I4s", data[offset:offset+8])
        body = data[offset+8:offset+8+length]
        if kind == b"IHDR":
            width, height, depth, colour = struct.unpack(">IIBB", body[:10])
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break
        offset += 12 + length
    assert depth == 8 and colour in (2, 6), f"unsupported PNG depth/colour {depth}/{colour}"
    channels = 3 if colour == 2 else 4
    raw = zlib.decompress(bytes(idat))
    stride = width*channels
    rows, previous = [], bytearray(stride)
    position = 0
    for _ in range(height):
        filter_type = raw[position]; position += 1
        line = bytearray(raw[position:position+stride]); position += stride
        for i in range(stride):
            left = line[i-channels] if i >= channels else 0
            up = previous[i]
            corner = previous[i-channels] if i >= channels else 0
            if filter_type == 1: line[i] = (line[i]+left) & 0xFF
            elif filter_type == 2: line[i] = (line[i]+up) & 0xFF
            elif filter_type == 3: line[i] = (line[i]+(left+up)//2) & 0xFF
            elif filter_type == 4:
                p = left+up-corner
                pa, pb, pc = abs(p-left), abs(p-up), abs(p-corner)
                line[i] = (line[i]+(left if pa <= pb and pa <= pc else up if pb <= pc else corner)) & 0xFF
        rows.append(bytes(line)); previous = line
    return width, height, channels, rows


def is_sky(pixel):
    """Sky and clouds: blue-dominant or near-white. Everything else counts as solid."""
    r, g, b = pixel
    return (b > r+24 and b > 120) or (r > 200 and g > 200 and b > 200)


def surface_rows(path):
    """Topmost row of the unbroken solid region at the bottom of each column."""
    width, height, channels, rows = read_png(path)
    tops = []
    for x in range(width):
        top = height
        for y in range(height-1, min(SKY_ROWS)-1, -1):
            pixel = rows[y][x*channels:x*channels+3]
            if is_sky(pixel):
                break
            top = y
        tops.append(top)
    return tops


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("captures", type=Path, nargs="+")
    ap.add_argument("--out", type=Path, default=Path("data/terrain_profile.json"))
    args = ap.parse_args()
    samples, sources = {}, []
    for capture in args.captures:
        count = 0
        for row, raw in captures(capture):
            scroll = int.from_bytes(raw[SCROLL:SCROLL+2], "little")
            for x, top in enumerate(surface_rows(capture / row["screenshot"])):
                samples.setdefault(scroll+x, []).append(top)
            count += 1
        sources.append({"capture": capture.name, "frames": count})
    profile = {position: statistics.median(tops) for position, tops in samples.items() if len(tops) >= 3}
    covered = sorted(profile)
    args.out.write_text(json.dumps({
        "status": "measured ground surface; median over frames removes moving sprites",
        "scroll_address": f"0x{SCROLL:04X}", "sources": sources,
        "level_x_range": [covered[0], covered[-1]] if covered else None,
        "surface_top_y": {str(k): profile[k] for k in covered}}, separators=(",", ":"))+"\n")
    print(json.dumps({"level_x_covered": len(covered), "range": [covered[0], covered[-1]] if covered else None,
                      "median_surface": statistics.median(profile.values()) if profile else None,
                      "highest_surface": min(profile.values()) if profile else None, "out": str(args.out)}, indent=2))


if __name__ == "__main__":
    main()
