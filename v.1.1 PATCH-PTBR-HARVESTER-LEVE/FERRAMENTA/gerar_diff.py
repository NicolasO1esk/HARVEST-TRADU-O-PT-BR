#!/usr/bin/env python3
"""Gera patches de diferenca (.hvp) entre arquivos originais e traduzidos.

Uso: python gerar_diff.py <pasta original do jogo> <pasta traduzida> <pasta de saida>
As duas pastas devem ter HARVEST\\ e HARVEST_CD\\ (ou as ISOs na raiz da traduzida).

Formato .hvp (todo o arquivo compactado com gzip):
  "HVP1"
  u64 tamanho final do arquivo
  u32 numero de trechos
  repetido: u64 offset, u32 tamanho, bytes
Os SHA-256 do original e do resultado ficam no MANIFESTO.csv da saida.
"""
import gzip
import hashlib
import struct
import sys
from pathlib import Path

ARQUIVOS = ["HARVEST/DIALOG.RSP", "HARVEST/MENU.INI", "HARVEST/HARVEST.EXE",
            "HARVEST_CD/HARVESTER_DISC1.ISO", "HARVEST_CD/HARVESTER_DISC2.ISO", "HARVEST_CD/HARVESTER_DISC3.ISO"]
BLOCO = 1 << 20
JUNTA = 64  # trechos separados por menos que isso viram um so


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(BLOCO), b""):
            h.update(b)
    return h.hexdigest().upper()


def trechos(orig, novo):
    """Gera (offset, bytes) das regioes diferentes; o que passa do tamanho original vai inteiro."""
    runs = []
    with open(orig, "rb") as fa, open(novo, "rb") as fb:
        pos = 0
        while True:
            a, b = fa.read(BLOCO), fb.read(BLOCO)
            if not b:
                break
            if a != b:
                n = min(len(a), len(b))
                i = 0
                while i < n:
                    if a[i] != b[i]:
                        j = i
                        while j < n and (a[j] != b[j] or (j + JUNTA < n and a[j:j + JUNTA] != b[j:j + JUNTA])):
                            j += 1
                        runs.append([pos + i, b[i:j]])
                        i = j
                    else:
                        i += 1
                if len(b) > n:
                    runs.append([pos + n, b[n:]])
            pos += len(b)
    merged = []
    for off, data in runs:
        if merged and off <= merged[-1][0] + len(merged[-1][1]):
            merged[-1][1] = merged[-1][1] + data[merged[-1][0] + len(merged[-1][1]) - off:]
        else:
            merged.append([off, data])
    return merged


def main():
    orig_dir, novo_dir, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    out.mkdir(parents=True, exist_ok=True)
    linhas = []
    for rel in ARQUIVOS:
        o = orig_dir / rel
        n = novo_dir / rel
        if not n.exists():
            n = novo_dir / Path(rel).name
        runs = trechos(o, n)
        nome = Path(rel).name + ".hvp"
        with gzip.open(out / nome, "wb", compresslevel=9) as g:
            g.write(b"HVP1")
            g.write(struct.pack("<QI", n.stat().st_size, len(runs)))
            for off, data in runs:
                g.write(struct.pack("<QI", off, len(data)))
                g.write(data)
        so, sn = sha(o), sha(n)
        linhas.append(f"{rel.replace('/', chr(92))},{nome},{so},{sn},{n.stat().st_size}")
        total = sum(len(d) for _, d in runs)
        print(f"{rel}: {len(runs)} trechos, {total:,} bytes -> {nome} {(out / nome).stat().st_size:,} bytes")
    (out / "MANIFESTO.csv").write_text("\n".join(linhas) + "\n", encoding="ascii")


if __name__ == "__main__":
    main()
