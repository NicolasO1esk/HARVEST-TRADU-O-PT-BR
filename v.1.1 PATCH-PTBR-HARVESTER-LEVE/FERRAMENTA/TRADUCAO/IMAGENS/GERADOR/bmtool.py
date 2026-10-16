"""Inspect / convert Harvester .BM payloads (from xfle unpack) to PNG.

Usage:
  bmtool.py info <file.bm>...
  bmtool.py png <file.bm> <palette.pal> <out.png>
Header hypothesis: uint32 width, uint32 height, uint32 flag, then pixels (8-bit indices).
"""
import struct
import sys
import zlib


def info(path):
    d = open(path, "rb").read()
    w, h, f = struct.unpack_from("<III", d)
    raw = 12 + w * h
    print(f"{path.split(chr(92))[-1]:16s} size={len(d):7d} w={w} h={h} flag=0x{f:X} raw12+wh={raw} sobra={len(d) - raw}")


def write_png(path, w, h, rows_rgb):
    def chunk(t, data):
        c = struct.pack(">I", len(data)) + t + data
        return c + struct.pack(">I", zlib.crc32(t + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + r for r in rows_rgb)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    open(path, "wb").write(png)


def to_png(bm, pal, out):
    d = open(bm, "rb").read()
    w, h, f = struct.unpack_from("<III", d)
    p = open(pal, "rb").read()[:768]
    scale = 4 if max(p) < 64 else 1
    pal3 = [bytes(min(255, c * scale) for c in p[i * 3:i * 3 + 3]) for i in range(256)]
    px = d[12:12 + w * h]
    rows = [b"".join(pal3[b] for b in px[y * w:(y + 1) * w]) for y in range(h)]
    write_png(out, w, h, rows)
    print("ok", out, w, h)


if __name__ == "__main__":
    if sys.argv[1] == "info":
        for f in sys.argv[2:]:
            info(f)
    else:
        to_png(*sys.argv[2:5])
