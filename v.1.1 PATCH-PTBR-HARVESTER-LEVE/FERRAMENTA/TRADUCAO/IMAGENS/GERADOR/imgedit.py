"""Edit UI bitmaps (BM inside HARVEST.DAT): erase text areas and redraw in Portuguese with game fonts.

Usage: imgedit.py <DAT> <outdir> [ONLY_NAME]
Writes <outdir>/<NAME>.BM (edited, same size), <outdir>/<NAME>.orig.sha256 and preview PNGs.
"""
import hashlib
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from bmtool import write_png  # noqa: E402
from cft import Font, read_records  # noqa: E402

dat = open(sys.argv[1], "rb").read()
out = Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
only = sys.argv[3].upper() if len(sys.argv) > 3 else None
recs = read_records(dat)


def rec(name):
    k = next(k for k in recs if k.endswith("\\" + name.upper()))
    hl, size = recs[k][0]
    return k, dat[hl:hl + size]


FONTS = {n: Font(rec(n + ".CFT")[1]) for n in ("TEXTFONT", "MEDFONT1", "SMALFONT", "HARVFONT")}
for _n in ("MEDFONT1", "SMALFONT", "HARVFONT"):
    FONTS[_n].fallback = FONTS["TEXTFONT"]
PALS = {}


def pal_for(name, fallback="LOADGAME"):
    for n in (Path(name).stem, fallback):
        try:
            p = rec(n + ".PAL")[1][:768]
            return [bytes(min(255, c * 4) for c in p[i * 3:i * 3 + 3]) for i in range(256)]
        except StopIteration:
            continue


# ops: ("fill", x0, y0, x1, y1, idx)            -> retangulo inclusivo pintado com idx
#      ("text", font, cx, y, "texto", gap)      -> texto centralizado em cx (cores nativas da fonte)
#      ("textl", font, x, y, "texto", gap)      -> texto alinhado a esquerda
#      ("recolor", x0, y0, x1, y1, {de: para})  -> troca indices numa area
SPECS = {
    "LOADGAME.BM": [
        ("fill", 8, 3, 631, 16, 1), ("text", "TEXTFONT", 320, 5, "CARREGAR JOGO", 1),
        ("fill", 8, 460, 314, 475, 1), ("text", "TEXTFONT", 160, 463, "Escolha um jogo para carregar", 1),
        ("fill", 326, 460, 631, 475, 1), ("text", "TEXTFONT", 480, 463, "CANCELAR", 1),
    ],
    "SAVEGAME.BM": [
        ("fill", 8, 3, 631, 16, 1), ("text", "TEXTFONT", 320, 5, "SALVAR JOGO", 1),
        ("fill", 8, 460, 314, 475, 1), ("text", "TEXTFONT", 160, 463, "SALVAR", 1),
        ("fill", 326, 460, 631, 475, 1), ("text", "TEXTFONT", 480, 463, "CANCELAR", 1),
    ],
    "TIPS.BM": [("fill", 40, 4, 265, 14, 3), ("text", "TEXTFONT", 153, 4, "DICAS DE JOGO", 1)],
    "KEYWORD.BM": [("fill", 100, 3, 205, 15, 3), ("text", "TEXTFONT", 153, 4, "Palavra-Chave", 1)],
    "RESPONSE.BM": [("fill", 100, 3, 205, 15, 3), ("text", "TEXTFONT", 153, 4, "Respostas", 1)],
}
INV = [
    ("clone", 30, 3, 93, 16, 96, 3, 127, 16),                       # apaga "25 CENTS"
    ("textc", "TEXTFONT", 61, 5, "25 CENTAVOS", 1, 24, 19),
    ("clone", 401, 3, 507, 16, 420, 16, 495, 24),                   # apaga "SPRING 1953"
    ("textc", "TEXTFONT", 455, 5, "PRIMAVERA 1953", 0, 24, 19),
    ("clone", 430, 22, 490, 44, 430, 46, 490, 58),                  # apaga "EXIT"
    ("textc", "MEDFONT1", 459, 25, "SAIR", 2, 24, 19),
]
SPECS["INVENTRY.BM"] = INV
SPECS["INVNTORY.BM"] = INV
SPECS["CONVBOX.BM"] = [("fill", 186, 100, 279, 110, 25), ("textr", "TEXTFONT", 277, 99, "DIGITAR:", 1, 1)]
for n in ("CD1.BM", "CD2.BM", "CD3.BM"):
    SPECS[n] = [("fill", 0, 450, 639, 479, 14),
                ("textc", "MEDFONT1", 320, 456, "APERTE CTRL+F4 E CLIQUE COM O BOTAO ESQUERDO", 1, 1)]


def apply(name, ops):
    try:
        key, data = rec(name)
    except StopIteration:
        print("ausente", name)
        return
    w, h, flag = struct.unpack_from("<III", data)
    img = bytearray(data[12:12 + w * h])
    for op in ops:
        if op[0] == "fill":
            _, x0, y0, x1, y1, c = op
            for y in range(y0, y1 + 1):
                img[y * w + x0:y * w + x1 + 1] = bytes([c]) * (x1 - x0 + 1)
        elif op[0] in ("text", "textl"):
            _, fn, x, y, s, gap = op
            f = FONTS[fn]
            if op[0] == "text":
                x = x - f.text_width(s, gap) // 2
            f.draw(img, w, x, y, s, 15, gap, shade=lambda v: v)
        elif op[0] in ("textc", "textr"):
            _, fn, x, y, s, gap, color = op[:7]
            halo = op[7] if len(op) > 7 else None
            f = FONTS[fn]
            tw = f.text_width(s, gap)
            x = x - tw // 2 if op[0] == "textc" else x - tw
            if halo is not None:
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    f.draw(img, w, x + dx, y + dy, s, halo, gap)
            f.draw(img, w, x, y, s, color, gap)
        elif op[0] == "clone":
            _, x0, y0, x1, y1, sx0, sy0, sx1, sy1 = op
            sw, sh = sx1 - sx0, sy1 - sy0
            src = bytes(img)
            for y in range(y0, y1 + 1):
                for x in range(x0, x1 + 1):
                    img[y * w + x] = src[(sy0 + (y - y0) % sh) * w + sx0 + (x - x0) % sw]
        elif op[0] == "recolor":
            _, x0, y0, x1, y1, m = op
            for y in range(y0, y1 + 1):
                for x in range(x0, x1 + 1):
                    v = img[y * w + x]
                    if v in m:
                        img[y * w + x] = m[v]
    new = data[:12] + bytes(img) + data[12 + w * h:]
    assert len(new) == len(data)
    stem = name.upper()
    orig_sha = hashlib.sha256(data).hexdigest().upper()
    (out / stem).write_bytes(new)
    (out / f"{orig_sha}.BM").write_bytes(new)
    with open(out / "MANIFESTO.csv", "a", encoding="ascii") as mf:
        mf.write(f"{orig_sha},{hashlib.sha256(new).hexdigest().upper()},{key}\n")
    pal = pal_for(name)
    rows = [b"".join(pal[v] for v in img[y * w:(y + 1) * w]) for y in range(h)]
    write_png(str(out / (Path(stem).stem + "_pt.png")), w, h, rows)
    print("ok", key, f"{w}x{h}")


for name, ops in SPECS.items():
    if only and name != only:
        continue
    apply(name, ops)
