"""Harvester CFT font reader + text renderer (mask-based).

CFT layout (confirmed on TEXTFONT): name[64]; u16 @64 (height-ish);
u16 start[256] @66; u16 width[256] @578; u16 @1090; u16 @1092..1094;
BM @1096: u32 w, u32 h, u32 flag, w*h pixels (glyph strip).
"""
import re
import struct


def read_records(dat):
    recs = {}
    for m in re.finditer(rb"XFLE.:(\\[^\x00]{1,120})\x00", dat, re.S):
        off = m.start()
        hl, size, z, s2 = struct.unpack_from("<IIII", dat, off + 132)
        if hl == off + 148 and size == s2:
            recs.setdefault(m.group(1).decode("latin-1").upper(), []).append((hl, size))
    return recs


class Font:
    def __init__(self, data):
        self.start = struct.unpack_from("<256H", data, 66)
        self.width = struct.unpack_from("<256H", data, 578)
        self.space = struct.unpack_from("<H", data, 1090)[0]
        self.w, self.h, _ = struct.unpack_from("<III", data, 1096)
        self.px = data[1108:1108 + self.w * self.h]

    def glyph(self, ch):
        c = ord(ch)
        return self.start[c], self.width[c]

    def text_width(self, s, gap=1):
        tot = 0
        for ch in s:
            if ch == " ":
                tot += self.space or 6
            elif ch == "+" and self.glyph(ch)[1] == 0:
                tot += self.glyph("-")[1] + gap
            elif self.glyph(ch)[1] == 0 and self.fallback is not None:
                tot += self.fallback.text_width(ch, gap)
            else:
                tot += self.glyph(ch)[1] + gap
        return tot

    fallback = None  # Font usada para caracteres ausentes (largura 0)

    def draw(self, img, iw, x, y, s, color, gap=1, shade=None):
        """Draw onto bytearray img (width iw). Glyph pixel != 0 -> color (or shade(map))."""
        for ch in s:
            if ch == " ":
                x += self.space or 6
                continue
            sx, gw = self.glyph(ch)
            if ch == "+" and gw == 0:
                # "+" sintetico: o "-" da fonte com uma barra vertical no meio
                msx, mw = self.glyph("-")
                rows = [yy for yy in range(self.h) if any(self.px[yy * self.w + msx + i] for i in range(mw))]
                if rows:
                    cy, cx = rows[len(rows) // 2], mw // 2
                    v = next(self.px[rows[0] * self.w + msx + i] for i in range(mw) if self.px[rows[0] * self.w + msx + i])
                    self.draw(img, iw, x, y, "-", color, gap, shade)
                    for yy in range(cy - mw // 2, cy + mw // 2 + 1):
                        for th in rows:
                            pos = (y + yy) * iw + x + cx + (th - rows[0])
                            if 0 <= pos < len(img):
                                img[pos] = shade(v) if shade else color
                    x += mw + gap
                    continue
            if gw == 0 and self.fallback is not None:
                fb = self.fallback
                x = fb.draw(img, iw, x, y + (self.h - fb.h) // 2, ch, color, gap, shade)
                continue
            for yy in range(self.h):
                row = yy * self.w
                for xx in range(gw):
                    v = self.px[row + sx + xx]
                    if v and 0 <= x + xx < iw and 0 <= y + yy and (y + yy) * iw + x + xx < len(img):
                        img[(y + yy) * iw + x + xx] = shade(v) if shade else color
            x += gw + gap
        return x
