#!/usr/bin/env python3
"""Ferramentas de texto do Harvester: mapear, exportar, construir e gravar em ISO.

Formatos confirmados (ver LOG-ANALISE-TRADUCAO.txt):
  * DIALOG.RSP   texto ASCII CRLF; o EXE abre a linha N (base 1); "/" separa
                 opcoes. Lido de C:\\HARVEST.
  * DIALOGUE.IDX XOR 0xAA (CR/LF preservados); pares "ID" / linha exibida
                 (com aspas). Lido do CD (D:).
  * HARVEST.SCR  XOR 0xAA (CR/LF preservados); script com TEXT/OBJECT/NPC,
                 "_" no lugar de espaco. Arquivo solto no CD.
  * MENU.INI     chave=valor; lido de C:\\HARVEST.
  * HARVEST.EXE  textos fixos ("Examine the %s"...) editados no lugar, sem
                 passar do tamanho original.

Comandos:
  mapear-exe  gera o mapa falas/menus a partir do HARVEST.EXE
  exportar    gera planilhas CSV de traducao (RSP, IDX, SCR, MENU, EXE)
  construir   gera arquivos traduzidos a partir das planilhas
  gravar-iso  copia uma ISO substituindo arquivos (tamanho pode mudar)
  aplicar     gera o patch completo: pasta HARVEST + 3 ISOs + .conf
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import shutil
import struct
import sys
from bisect import bisect_left
from collections import Counter, defaultdict
from pathlib import Path

SECTOR = 2048
CSV_ENCODING = "utf-8-sig"


# ---------------------------------------------------------------- utilidades

def xor_aa(data: bytes) -> bytes:
    """Cifra/decifra XOR 0xAA preservando CR e LF (a operacao e simetrica)."""
    return bytes(b if b in (0x0D, 0x0A) else b ^ 0xAA for b in data)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def split_crlf(data: bytes) -> tuple[list[str], str]:
    """Separa em linhas CRLF; o resto apos o ultimo CRLF (ex.: NUL final) e preservado."""
    parts = data.decode("ascii").split("\r\n")
    return parts[:-1], parts[-1]


def join_crlf(lines: list[str], tail: str = "") -> bytes:
    return ("".join(line + "\r\n" for line in lines) + tail).encode("ascii")


def check_ascii(text: str, where: str) -> list[str]:
    """Restricao do projeto: somente ASCII imprimivel, sem acentos."""
    bad = sorted({c for c in text if not (0x20 <= ord(c) <= 0x7E)})
    return [f"{where}: caracteres nao permitidos {bad!r} (use ASCII sem acentos)"] if bad else []


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding=CSV_ENCODING) as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding=CSV_ENCODING) as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------- IDX

def parse_idx(plain: bytes) -> list[tuple[int, str]]:
    lines, tail = split_crlf(plain)
    if tail:
        raise ValueError("DIALOGUE.IDX com bytes apos o ultimo CRLF")
    if len(lines) % 2:
        raise ValueError("DIALOGUE.IDX com numero impar de linhas")
    out = []
    for i in range(0, len(lines), 2):
        if not lines[i].isdigit():
            raise ValueError(f"linha {i + 1} do IDX deveria ser um ID: {lines[i]!r}")
        out.append((int(lines[i]), lines[i + 1]))
    return out


def unquote(raw: str) -> tuple[str, bool]:
    if len(raw) >= 2 and raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1], True
    return raw, False


# ---------------------------------------------------------------- SCR

SCR_TEXT = re.compile(r'^(\s*-?\d+\s+-?\d+\s+TEXT\s+"([^"]*)"\s+"([^"]*)"\s+")([^"]*)(".*)$')
QUOTED = re.compile(r'"([^"]*)"')


def scr_items(lines: list[str]):
    """Gera (n_linha, tipo, id, caixa, inicio, fim) dos textos traduziveis ativos."""
    for n, line in enumerate(lines):
        if line.lstrip().startswith("{"):
            continue
        m = SCR_TEXT.match(line)
        if m:
            yield n, "TEXT", m.group(2), m.group(3), m.start(4), m.end(4)
            continue
        kw = re.match(r"^\s*(?:-?\d+\s+)*(OBJECT|NPC)\s", line)
        if kw:
            fields = list(QUOTED.finditer(line))
            if len(fields) >= 2 and fields[-1].group(1):
                ident = fields[1].group(1)
                last = fields[-1]
                yield n, "NOME_" + kw.group(1), ident, "", last.start(1), last.end(1)
            continue
        # nome de lugar no mapa da cidade: MAP_LOCATION "Nome_Exibido" "ID"
        if re.match(r"^\s*(?:-?\d+\s+)*MAP_LOCATION\s", line):
            fields = list(QUOTED.finditer(line))
            if len(fields) >= 2 and fields[0].group(1):
                yield n, "NOME_MAPA", fields[1].group(1), "", fields[0].start(1), fields[0].end(1)


def scr_to_display(raw: str) -> str:
    return raw.replace("_", " ")


def display_to_scr(text: str) -> str:
    return text.replace(" ", "_")


# Medido no teste 11 (regua): 13 numeros "NN " por linha = 38 caracteres
# (fonte de largura fixa); BOX1=1, BOX2=2, BOX3=3, BOX4=5 linhas na moldura.
LINE_WIDTH = 38
BOX_LINES = {"BOX1": 1, "BOX2": 2, "BOX3": 3, "BOX4": 5}


def wrapped_lines(text: str, width: int = LINE_WIDTH) -> int:
    """Linhas ocupadas com quebra por palavra (palavra maior que a linha conta inteira)."""
    lines, cur = 0, -1
    for word in text.split():
        if cur >= 0 and cur + 1 + len(word) <= width:
            cur += 1 + len(word)
        else:
            lines += 1
            cur = len(word)
    return max(lines, 1)


def box_for(lines: int) -> str | None:
    return next((b for b, n in sorted(BOX_LINES.items(), key=lambda x: x[1]) if n >= lines), None)


# ---------------------------------------------------------------- topicos do RSP

# Linhas do RSP sem "1." sao listas de topicos ("Stephanie/Hank/Job") ou
# palavras-chave em MAIUSCULAS ("HANK"). O EXE reconhece o topico escolhido
# com stricmp (rotina 0xE1D8E: igualdade exata, sem diferenciar maiusculas),
# contra palavras-chave do RSP e contra textos fixos do EXE ("BYE" encerra a
# conversa). Por isso: GLOSSARIO unico; textos iguais em ingles continuam
# iguais, diferentes continuam diferentes; textos fixos do EXE comparados com
# topicos recebem a traducao do glossario automaticamente (sem passar do
# tamanho original).
STRICMP_ROUTINE = 0xE1D8E
TOPIC_EXE_LITERALS = (0x0F6609, 0x0F660F, 0x0F6624, 0x0F6F9D, 0x0F91A0, 0x0F91CA, 0x0F91E6)
# "Lodge", "The Lodge", "BYE", "Arsonist", "LOOMIS", "Phelps", "Man's Needs"


def is_option_line(line: str) -> bool:
    return bool(re.match(r"^\s*1\.", line))


def topic_tokens(rsp: list[str]):
    """Gera (n_linha_base1, [tokens]) das linhas de topico."""
    for n, line in enumerate(rsp, 1):
        if not is_option_line(line):
            yield n, line.split("/")


def glossary_lookup(gloss: dict[str, str], token: str) -> str | None:
    core = token.strip()
    if not core:
        return None
    tr = gloss.get(core)
    if tr is None:
        tr = next((v for k, v in gloss.items() if k.upper() == core.upper()), None)
    if tr is None:
        return None
    if core.isupper():
        tr = tr.upper()
    elif core.islower():
        tr = tr.lower()
    return token[:len(token) - len(token.lstrip())] + tr + token[len(token.rstrip()):]


MENU_BLOCK_FIRST_LINE = 784  # RSP 784..806: textos de menu (YES/NO/ON/OFF...), fora das conversas


def check_topic_matching(pairs_en: list[str], pairs_tr: list[str]) -> list[str]:
    """Iguais (sem diferenciar maiusculas) em ingles <=> iguais na traducao."""
    errors = []
    groups: dict[str, set[str]] = defaultdict(set)
    for en, tr in zip(pairs_en, pairs_tr):
        if en.strip():
            groups[en.strip().upper()].add(tr.strip().upper())
    for en, trs in groups.items():
        if len(trs) > 1:
            errors.append(f"TOPICOS: '{en}' recebeu traducoes diferentes {sorted(trs)}")
    owner: dict[str, str] = {}
    for en, trs in groups.items():
        for tr in trs:
            if tr in owner and owner[tr] != en:
                errors.append(f"TOPICOS: '{owner[tr]}' e '{en}' sao diferentes em ingles, mas ambos viraram "
                              f"'{tr}' (o jogo passaria a confundir os dois)")
            owner.setdefault(tr, en)
    return errors


# ---------------------------------------------------------------- MENU.INI

def menu_items(lines: list[str]):
    """Gera (n_linha, chave, valor) das linhas chave=valor."""
    for n, line in enumerate(lines):
        if "=" in line and not line.lstrip().startswith((";", "[")):
            key, value = line.split("=", 1)
            yield n, key, value


# ---------------------------------------------------------------- textos fixos do EXE

# Offsets de arquivo no HARVEST.EXE instalado (SHA-256 6A9F3844...). Somente
# textos que o jogador pode ver; mensagens de erro/depuracao ficaram de fora.
EXE_TEXTS = [
    (0x1010FF, "acao do mouse"), (0x101138, "acao do mouse"),
    (0x1011DE, "acao do mouse"), (0x1011F1, "acao do mouse (confirmado: 'Examine the ANTENA D')"),
    (0x101208, "acao do mouse"), (0x10121B, "acao do mouse"), (0x101255, "acao do mouse"),
    (0x10139D, "acao do mouse (2a copia)"), (0x1013B0, "acao do mouse (2a copia)"),
    (0x1013C7, "acao do mouse (2a copia)"), (0x1013DA, "acao do mouse (2a copia)"),
    (0x1013F1, "acao do mouse (2a copia)"),
    (0x102776, "acao do mouse (inventario)"), (0x1027A4, "acao do mouse (inventario)"),
    (0x1027AE, "acao do mouse (inventario)"), (0x1027C7, "acao do mouse (inventario)"),
    (0x101F5C, "titulo da caixa de respostas"),
    (0x0FD115, "inventario"),
    (0x102C9D, "armas"), (0x102CB3, "armas"), (0x102CCA, "armas"), (0x102CE2, "armas"),
    (0x102CFB, "armas"), (0x102D14, "armas"), (0x102D29, "armas"),
    (0x10693C, "tela de pausa (espacos centralizam)"),
    (0x106844, "texto de transicao (troca de disco?)"),
    (0x1006BD, "senha parental"),
    (0x0F521D, "opcao de dialogo fixa no EXE (/ separa opcoes)"),
    (0x0F5270, "opcao de dialogo fixa no EXE (/ separa opcoes)"),
    (0x0F6587, "opcao de dialogo fixa no EXE (/ separa opcoes)"),
    (0x100669, "menu de opcoes: sufixo ligado"), (0x100676, "menu de opcoes: sufixo ligado"),
    (0x10066F, "menu de opcoes: sufixo desligado"), (0x10067C, "menu de opcoes: sufixo desligado"),
    (0x0F2DF7, "calibracao do joystick"), (0x0F2E0E, "calibracao do joystick"),
    (0x0F2E1F, "calibracao do joystick"), (0x0F2E38, "calibracao do joystick"),
    (0x1054AC, "calibracao do joystick (direcao)"), (0x1054BB, "calibracao do joystick (direcao)"),
    (0x1054CA, "calibracao do joystick (direcao)"), (0x1054D9, "calibracao do joystick (direcao)"),
    (0x0FBD3E, "aviso de CD"), (0x0FBD63, "aviso de CD"),
    # "The Lodge"/"Man's Needs" sao topicos comparados por stricmp: vem do glossario
]
PRINTF = re.compile(r"%[-+ #0-9.]*[a-zA-Z]")


def exe_text_at(exe: bytes, off: int) -> str:
    end = exe.index(b"\x00", off)
    return exe[off:end].decode("latin-1")


# ---------------------------------------------------------------- EXE (LE DOS/4GW)

class LEImage:
    def __init__(self, data: bytes):
        self.d = data
        le = data.find(b"LE\x00\x00", 0x40000)
        mz = next(m for m in range(0, le, 2)
                  if data[m:m + 2] == b"MZ" and struct.unpack_from("<I", data, m + 0x3C)[0] == le - m)
        page = struct.unpack_from("<I", data, le + 0x28)[0]
        pages_off = mz + struct.unpack_from("<I", data, le + 0x80)[0]
        tab = le + struct.unpack_from("<I", data, le + 0x40)[0]
        objs = [struct.unpack_from("<6I", data, tab + i * 24) for i in range(3)]
        self.cs = pages_off + (objs[0][3] - 1) * page
        self.ce = self.cs + objs[0][4] * page
        self.ds = pages_off + (objs[2][3] - 1) * page
        self.dl = objs[2][4] * page

    def name(self, v):
        if v is None or not 0 <= v < self.dl:
            return None
        o = self.ds + v
        e = self.d.find(b"\x00", o, o + 40)
        s = self.d[o:e] if e > o else b""
        return s.decode() if re.fullmatch(rb"[A-Z][A-Z0-9_]*", s) else None


REG = {0: "eax", 1: "ecx", 2: "edx", 3: "ebx", 6: "esi", 7: "edi"}
XOR_RR = {bytes([0x31, 0xC0 | (r << 3) | r]): REG[r] for r in REG}
REG_MOVES = {b"\x89\xd8", b"\x89\xc3", b"\x89\xf2", b"\x89\xfa", b"\x89\xf0", b"\x89\xd0"}
SPEAK_ROUTINE = 0xDAFC4  # offset de arquivo no HARVEST.EXE instalado
MENU_ROUTINE = 0x9AAD4


def regs_before(img: LEImage, pos: int) -> dict[str, int]:
    d, found, p = img.d, {}, pos
    for _ in range(8):
        if p - 5 >= img.cs and 0xB8 <= d[p - 5] <= 0xBF and (d[p - 5] - 0xB8) in REG:
            found.setdefault(REG[d[p - 5] - 0xB8], struct.unpack_from("<I", d, p - 4)[0])
            p -= 5
        elif d[p - 2:p] in XOR_RR:
            found.setdefault(XOR_RR[d[p - 2:p]], 0)
            p -= 2
        elif d[p - 2:p] in REG_MOVES:
            p -= 2
        else:
            break
    return found


def map_exe(exe: bytes, idx: dict[int, str], rsp: list[str]):
    img = LEImage(exe)
    rows = []
    for m in re.finditer(rb"\xe8(....)", exe[img.cs:img.ce], re.S):
        o = img.cs + m.start()
        t = o + 5 + struct.unpack("<i", m.group(1))[0]
        if t not in (SPEAK_ROUTINE, MENU_ROUTINE):
            continue
        r = regs_before(img, o)
        eax = r.get("eax")
        if t == SPEAK_ROUTINE:
            rows.append({"Tipo": "FALA", "OffsetArquivoEXE": f"0x{o:X}", "Falante": img.name(r.get("edx")) or "",
                         "Expressao": r.get("ebx", ""), "ID": "" if eax is None else eax,
                         "Texto": idx.get(eax, "") if eax is not None else "<ID calculado em execucao>"})
        else:
            ok = eax is not None and 1 <= eax <= len(rsp)
            rows.append({"Tipo": "MENU_RSP", "OffsetArquivoEXE": f"0x{o:X}", "Falante": "", "Expressao": "",
                         "ID": "" if eax is None else eax,
                         "Texto": rsp[eax - 1] if ok else "<linha calculada em execucao>"})
    return rows


def speakers_by_id(map_rows, idx_ids: list[int]) -> dict[int, tuple[str, str]]:
    """Falante direto (mapa) ou inferido pelos vizinhos (IDs agrupados por personagem)."""
    direct = defaultdict(Counter)
    for r in map_rows:
        if r["Tipo"] == "FALA" and str(r["ID"]).isdigit() and r["Falante"]:
            direct[int(r["ID"])][r["Falante"]] += 1
    known = sorted(direct)
    out = {}
    for i in idx_ids:
        if i in direct:
            out[i] = ("/".join(n for n, _ in direct[i].most_common()), "EXE")
            continue
        k = bisect_left(known, i)
        before = direct[known[k - 1]].most_common(1)[0][0] if k > 0 else None
        after = direct[known[k]].most_common(1)[0][0] if k < len(known) else None
        if before and before == after:
            out[i] = (before, "INFERIDO")
        else:
            out[i] = ("", "")
    return out


# ---------------------------------------------------------------- ISO9660

def iso_find_record(iso, path: str) -> tuple[int, int, int]:
    """Retorna (offset_do_registro_de_diretorio, extent, tamanho)."""
    iso.seek(16 * SECTOR)
    pvd = iso.read(SECTOR)
    if pvd[0] != 1 or pvd[1:6] != b"CD001":
        raise ValueError("descritor primario ISO9660 nao encontrado")
    extent = int.from_bytes(pvd[156 + 2:156 + 6], "little")
    size = int.from_bytes(pvd[156 + 10:156 + 14], "little")
    parts = [p for p in path.replace("/", "\\").split("\\") if p]
    for depth, part in enumerate(parts):
        iso.seek(extent * SECTOR)
        data = iso.read(size)
        pos, hit = 0, None
        while pos < len(data):
            ln = data[pos]
            if ln == 0:
                pos = (pos // SECTOR + 1) * SECTOR
                continue
            rec = data[pos:pos + ln]
            raw = rec[33:33 + rec[32]]
            if raw not in (b"\0", b"\1"):
                nm = raw.decode("ascii").split(";", 1)[0].rstrip(".")
                if nm.casefold() == part.casefold():
                    if hit is not None:
                        raise ValueError(f"nome duplicado na ISO: {part}")
                    hit = (extent * SECTOR + pos, int.from_bytes(rec[2:6], "little"),
                           int.from_bytes(rec[10:14], "little"), rec[25])
            pos += ln
        if hit is None:
            raise FileNotFoundError(f"{part} nao encontrado na ISO")
        rec_off, extent, size, flags = hit
        if depth < len(parts) - 1 and not flags & 2:
            raise NotADirectoryError(part)
        if depth == len(parts) - 1 and flags & 2:
            raise IsADirectoryError(part)
    return rec_off, extent, size


def both_endian(v: int) -> bytes:
    return v.to_bytes(4, "little") + v.to_bytes(4, "big")


def iso_replace(iso_path: Path, path_in_iso: str, new: bytes, force_append: bool = False) -> str:
    with iso_path.open("r+b") as iso:
        rec_off, extent, old_size = iso_find_record(iso, path_in_iso)
        allocated = -(-old_size // SECTOR) * SECTOR
        if force_append:
            allocated = -1
        iso.seek(0, 2)
        end = iso.tell()
        if len(new) <= allocated:
            where = extent
            how = f"no lugar (setor {extent}; {len(new)}/{allocated} bytes alocados)"
        else:
            where = -(-end // SECTOR)
            how = f"anexado ao fim da imagem (setor {where}; antigo setor {extent} fica sem uso)"
        if len(new) <= allocated:
            # no lugar: so zera o trecho que o arquivo antigo ocupava alem do novo;
            # a sobra do ultimo setor fica como estava na ISO original
            padded = new + b"\0" * max(0, old_size - len(new))
        else:
            padded = new + b"\0" * (-len(new) % SECTOR)
        iso.seek(where * SECTOR)
        iso.write(padded)
        iso.seek(rec_off + 2)
        iso.write(both_endian(where))
        iso.seek(rec_off + 10)
        iso.write(both_endian(len(new)))
        # tamanho do volume: so cresce se o arquivo ficou alem do volume declarado
        used_end = where + -(-len(new) // SECTOR)
        iso.seek(16 * SECTOR + 80)
        old_vol = int.from_bytes(iso.read(4), "little")
        if used_end > old_vol:
            iso.seek(16 * SECTOR + 80)
            iso.write(both_endian(used_end))
        # verificacao
        _, ext2, size2 = iso_find_record(iso, path_in_iso)
        iso.seek(ext2 * SECTOR)
        if iso.read(size2) != new:
            raise RuntimeError(f"verificacao falhou para {path_in_iso}")
    return how


# ---------------------------------------------------------------- comandos

def cmd_mapear_exe(a) -> int:
    idx = dict(parse_idx(xor_aa(a.idx.read_bytes())))
    rsp, _ = split_crlf(a.rsp.read_bytes())
    rows = map_exe(a.exe.read_bytes(), idx, rsp)
    write_csv(a.saida, list(rows[0].keys()), [list(r.values()) for r in rows])
    fala_ids = {r["ID"] for r in rows if r["Tipo"] == "FALA" and r["ID"] != ""} & set(idx)
    menu_ids = {r["ID"] for r in rows if r["Tipo"] == "MENU_RSP" and r["ID"] != ""}
    print(f"Mapa: {a.saida}")
    print(f"Chamadas de fala: {sum(r['Tipo'] == 'FALA' for r in rows)}; IDs do IDX distintos: {len(fala_ids)} de {len(idx)}")
    print(f"Chamadas de menu: {sum(r['Tipo'] == 'MENU_RSP' for r in rows)}; linhas do RSP distintas: {len(menu_ids)} de {len(rsp)}")
    return 0


KEEP_COLUMNS = ("Traducao", "NovaCaixa")
CSV_KEYS = {"GLOSSARIO-TOPICOS.csv": ("Original",),
            "TRADUCAO-RSP.csv": ("Linha", "Original"), "TRADUCAO-IDX.csv": ("ID", "Original"),
            "TRADUCAO-SCR.csv": ("Tipo", "Original"), "TRADUCAO-MENU.csv": ("Chave", "Original"),
            "TRADUCAO-EXE.csv": ("Offset", "Original")}


def write_csv_keeping(path: Path, header: list[str], rows: list[list]) -> int:
    """Grava a planilha mantendo Traducao/NovaCaixa ja preenchidas (casadas por chave+Original)."""
    kept = {}
    if path.exists():
        key = CSV_KEYS[path.name]
        for r in read_csv(path):
            vals = {c: r.get(c, "") for c in KEEP_COLUMNS if r.get(c, "")}
            if vals:
                kept[tuple(r[k] for k in key)] = vals
    used = 0
    if kept:
        key_idx = [header.index(k) for k in CSV_KEYS[path.name]]
        for row in rows:
            vals = kept.pop(tuple(str(row[i]) for i in key_idx), None)
            if vals:
                used += 1
                for c, v in vals.items():
                    if c in header:
                        row[header.index(c)] = v
    if kept:
        raise ValueError(f"{path.name}: {len(kept)} traducoes nao casaram com o original; nada foi gravado")
    write_csv(path, header, rows)
    return used


def cmd_exportar(a) -> int:
    out: Path = a.saida
    if out.exists() and any(out.iterdir()) and not a.force:
        raise FileExistsError(f"{out} ja tem arquivos; use --force (as traducoes ja feitas sao mantidas)")

    rsp, _ = split_crlf(a.rsp.read_bytes())
    menu_use = Counter()
    map_rows = read_csv(a.mapa) if a.mapa else []
    for r in map_rows:
        if r["Tipo"] == "MENU_RSP" and r["ID"].isdigit():
            menu_use[int(r["ID"])] += 1
    rows = []
    for n, line in enumerate(rsp, 1):
        rows.append([n, line.count("/") + 1, menu_use.get(n, 0), len(line), line, ""])
    write_csv_keeping(out / "TRADUCAO-RSP.csv",
                      ["Linha", "Partes", "UsosNoEXE", "Caracteres", "Original", "Traducao"], rows)

    # glossario de topicos: uma linha por topico; variantes MAIUSCULAS/minusculas
    # de um topico ja listado sao derivadas automaticamente
    occ: dict[str, list[int]] = defaultdict(list)
    for n, toks in topic_tokens(rsp):
        for t in toks:
            if t.strip():
                occ[t.strip()].append(n)
    mixed = {t.upper() for t in occ if not t.isupper() and not t.islower()}
    rows = []
    for t in sorted(occ, key=lambda x: (x.upper(), x)):
        if (t.isupper() or t.islower()) and t.upper() in mixed:
            continue
        lines_all = sorted({n for v in occ if v.upper() == t.upper() for n in occ[v]})
        kw = "SIM" if any(v.isupper() for v in occ if v.upper() == t.upper()) else ""
        rows.append([t, len(lines_all), kw, " ".join(map(str, lines_all[:12])), ""])
    write_csv_keeping(out / "GLOSSARIO-TOPICOS.csv",
                      ["Original", "Linhas", "TemPalavraChave", "OndeNoRSP", "Traducao"], rows)
    print(f"  Glossario de topicos: {len(rows)} entradas")

    idx = parse_idx(xor_aa(a.idx.read_bytes()))
    spk = speakers_by_id(map_rows, [i for i, _ in idx]) if map_rows else {}
    rows = []
    for i, raw in idx:
        text, quoted = unquote(raw)
        who, src = spk.get(i, ("", ""))
        rows.append([i, who, src, "SIM" if quoted else "NAO", len(text), text, ""])
    write_csv_keeping(out / "TRADUCAO-IDX.csv",
                      ["ID", "Falante", "FonteFalante", "EntreAspas", "Caracteres", "Original", "Traducao"], rows)

    groups: dict[tuple[str, str], dict] = {}
    for scr_path in a.scr:
        lines, _ = split_crlf(xor_aa(scr_path.read_bytes()))
        for n, kind, ident, box, s, e in scr_items(lines):
            raw = lines[n][s:e]
            g = groups.setdefault((kind, raw), {"caixas": set(), "ocorr": []})
            if box:
                g["caixas"].add(box)
            g["ocorr"].append(f"{scr_path.name}:{n + 1}:{ident}")
    rows = []
    for k, ((kind, raw), g) in enumerate(sorted(groups.items(), key=lambda x: (x[0][0], x[1]["ocorr"][0])), 1):
        rows.append([f"S{k:04d}", kind, "/".join(sorted(g["caixas"])), len(g["ocorr"]),
                     "; ".join(g["ocorr"][:6]) + (" ..." if len(g["ocorr"]) > 6 else ""),
                     len(raw), scr_to_display(raw), "", ""])
    write_csv_keeping(out / "TRADUCAO-SCR.csv",
                      ["Chave", "Tipo", "Caixa", "Ocorrencias", "Onde", "Caracteres", "Original",
                       "Traducao", "NovaCaixa"], rows)
    print(f"Planilhas em {out}: RSP {len(rsp)} linhas, IDX {len(idx)} falas, SCR {len(groups)} textos unicos")

    if a.menu:
        lines, _ = split_crlf(a.menu.read_bytes())
        rows = [[key, len(value), value, ""] for _, key, value in menu_items(lines)]
        write_csv_keeping(out / "TRADUCAO-MENU.csv", ["Chave", "Caracteres", "Original", "Traducao"], rows)
        print(f"  MENU.INI: {len(rows)} itens")
    if a.exe:
        exe = a.exe.read_bytes()
        rows = []
        for off, note in EXE_TEXTS:
            text = exe_text_at(exe, off)
            rows.append([f"0x{off:X}", len(text), note, text, ""])
        write_csv_keeping(out / "TRADUCAO-EXE.csv", ["Offset", "MaxCaracteres", "Nota", "Original", "Traducao"], rows)
        print(f"  HARVEST.EXE: {len(rows)} textos fixos")
    return 0


def build_texts(t: Path, rsp_bytes: bytes, idx_bytes: bytes, scrs: list[tuple[str, bytes]],
                menu_bytes: bytes | None = None, exe_bytes: bytes | None = None):
    """Aplica as planilhas. Retorna (erros, relatorio, {nome: bytes})."""
    errors, report = [], []

    # RSP
    rsp, rsp_tail = split_crlf(rsp_bytes)
    rsp_max_opt = max(len(p) for line in rsp for p in line.split("/"))
    changed = 0
    for r in read_csv(t / "TRADUCAO-RSP.csv"):
        tr = r["Traducao"]
        if not tr.strip():
            continue
        n = int(r["Linha"])
        orig = rsp[n - 1]
        if r["Original"] != orig:
            errors.append(f"RSP linha {n}: coluna Original difere do DIALOG.RSP de entrada")
            continue
        errors += check_ascii(tr, f"RSP linha {n}")
        if tr.count("/") != orig.count("/"):
            errors.append(f"RSP linha {n}: {orig.count('/') + 1} opcao(oes) no original, {tr.count('/') + 1} na traducao")
        if any(not p.strip() for p in tr.split("/")):
            errors.append(f"RSP linha {n}: opcao vazia")
        longest = max(len(p) for p in tr.split("/"))
        if longest > rsp_max_opt:
            report.append(f"  aviso RSP linha {n}: opcao com {longest} caracteres; a maior original tem "
                          f"{rsp_max_opt}. Confira no jogo")
        rsp[n - 1] = tr
        changed += 1
    report.append(f"RSP: {changed} linhas traduzidas de {len(rsp)}")

    # topicos pelo glossario (linhas de topico sem traducao explicita)
    explicit = {int(r["Linha"]) for r in read_csv(t / "TRADUCAO-RSP.csv") if r["Traducao"].strip()}
    exe_tr = {}
    if (t / "TRADUCAO-EXE.csv").exists():
        exe_tr = {int(r["Offset"], 16): r["Traducao"] for r in read_csv(t / "TRADUCAO-EXE.csv")}
    gpath = t / "GLOSSARIO-TOPICOS.csv"
    topic_exe: dict[int, tuple[str, str]] = {}
    if gpath.exists():
        gloss = {r["Original"]: r["Traducao"] for r in read_csv(gpath) if r["Traducao"].strip()}
        for k, v in gloss.items():
            errors += check_ascii(v, f"GLOSSARIO '{k}'")
            if "/" in v:
                errors.append(f"GLOSSARIO '{k}': '/' nao e permitida num topico")
        en_tok, tr_tok, glines = [], [], 0
        for n, toks in topic_tokens(rsp):
            if n in explicit:
                continue
            new = []
            for tok in toks:
                tr = glossary_lookup(gloss, tok)
                new.append(tok if tr is None else tr)
                if tok.strip() and n < MENU_BLOCK_FIRST_LINE:
                    en_tok.append(tok)
                    tr_tok.append(new[-1])
            if new != toks:
                rsp[n - 1] = "/".join(new)
                glines += 1
        # textos fixos do EXE comparados com topicos: traducao vem do glossario
        if exe_bytes is not None:
            for off in TOPIC_EXE_LITERALS:
                orig = exe_text_at(exe_bytes, off)
                tr = glossary_lookup(gloss, orig) or orig
                en_tok.append(orig)
                tr_tok.append(tr)
                if tr != orig:
                    if len(tr) > len(orig):
                        errors.append(f"GLOSSARIO '{orig}': o EXE compara o topico com o texto fixo '{orig}' "
                                      f"(0x{off:X}); a traducao '{tr}' passa de {len(orig)} caracteres")
                    else:
                        topic_exe[off] = (orig, tr)
        errors += check_topic_matching(en_tok, tr_tok)
        report.append(f"RSP: {glines} linhas de topico traduzidas pelo glossario ({len(gloss)} entradas); "
                      f"{len(topic_exe)} textos fixos do EXE sincronizados")

    # IDX
    idx = parse_idx(xor_aa(idx_bytes))
    idx_max_lines = max(wrapped_lines(raw) for _, raw in idx)
    pos = {i: k for k, (i, _) in enumerate(idx)}
    changed = 0
    for r in read_csv(t / "TRADUCAO-IDX.csv"):
        tr = r["Traducao"]
        if not tr.strip():
            continue
        i = int(r["ID"])
        k = pos[i]
        text, quoted = unquote(idx[k][1])
        if r["Original"] != text:
            errors.append(f"IDX {i}: coluna Original difere do DIALOGUE.IDX de entrada")
            continue
        errors += check_ascii(tr, f"IDX {i}")
        shown = f'"{tr}"' if quoted else tr
        if wrapped_lines(shown) > idx_max_lines:
            report.append(f"  aviso IDX {i}: {wrapped_lines(shown)} linhas; a maior fala original usa "
                          f"{idx_max_lines}. Confira no jogo ou encurte")
        idx[k] = (i, shown)
        changed += 1
    report.append(f"IDX: {changed} falas traduzidas de {len(idx)}")

    # SCR
    scr_tr, scr_box = {}, {}
    for r in read_csv(t / "TRADUCAO-SCR.csv"):
        tr = r["Traducao"]
        # chave pelo texto exibido: o original pode misturar "_" e espacos de verdade
        key = (r["Tipo"], r["Original"])
        box = r.get("NovaCaixa", "").strip().upper()
        if box:
            if r["Tipo"] != "TEXT" or not re.fullmatch(r"BOX[1-4]", box):
                errors.append(f"SCR {r['Chave']}: NovaCaixa deve ser BOX1..BOX4 e so vale para TEXT")
            scr_box[key[1]] = box
        if not tr.strip():
            continue
        errors += check_ascii(tr, f"SCR {r['Chave']}")
        if '"' in tr:
            errors.append(f"SCR {r['Chave']}: aspas (\") nao sao permitidas em textos do script")
        if "_" in tr:
            errors.append(f"SCR {r['Chave']}: use espacos, nao '_' (a ferramenta converte)")
        scr_tr[key] = display_to_scr(tr)
        if r["Tipo"] == "TEXT":
            need = wrapped_lines(tr)
            current = box or max(r["Caixa"].split("/"), key=lambda b: BOX_LINES.get(b, 0))
            if need > BOX_LINES.get(current, 0):
                auto = box_for(need)
                if auto is None:
                    errors.append(f"SCR {r['Chave']}: {need} linhas de {LINE_WIDTH} caracteres; "
                                  f"maximo {max(BOX_LINES.values())} (BOX4). Encurte o texto")
                else:
                    scr_box[key[1]] = auto
                    report.append(f"  aviso SCR {r['Chave']}: {need} linhas nao cabem em {current}; "
                                  f"caixa trocada para {auto}")

    # MENU.INI
    menu_lines = menu_tail = None
    if menu_bytes is not None and (t / "TRADUCAO-MENU.csv").exists():
        menu_lines, menu_tail = split_crlf(menu_bytes)
        by_key = {key: (n, value) for n, key, value in menu_items(menu_lines)}
        changed = 0
        for r in read_csv(t / "TRADUCAO-MENU.csv"):
            tr = r["Traducao"]
            if not tr.strip():
                continue
            n, value = by_key.get(r["Chave"], (None, None))
            if n is None or value != r["Original"]:
                errors.append(f"MENU {r['Chave']}: chave/Original difere do MENU.INI de entrada")
                continue
            errors += check_ascii(tr, f"MENU {r['Chave']}")
            menu_lines[n] = f"{r['Chave']}={tr}"
            changed += 1
        report.append(f"MENU.INI: {changed} itens traduzidos")

    # HARVEST.EXE (no lugar, sem passar do tamanho original)
    exe = None
    if exe_bytes is not None and topic_exe:
        exe = bytearray(exe_bytes)
        for off, (orig, tr) in topic_exe.items():
            raw = tr.encode("ascii")
            exe[off:off + len(orig)] = raw + b"\x00" * (len(orig) - len(raw))
    if exe_bytes is not None and (t / "TRADUCAO-EXE.csv").exists():
        exe = exe if exe is not None else bytearray(exe_bytes)
        changed = 0
        for r in read_csv(t / "TRADUCAO-EXE.csv"):
            tr = r["Traducao"]
            if not tr.strip():
                continue
            off = int(r["Offset"], 16)
            orig = r["Original"]
            if off in TOPIC_EXE_LITERALS:
                errors.append(f"EXE {r['Offset']}: este texto e um topico; traduza pelo GLOSSARIO-TOPICOS.csv")
                continue
            if exe_text_at(exe_bytes, off) != orig:
                errors.append(f"EXE {r['Offset']}: texto no EXE difere da coluna Original (EXE diferente?)")
                continue
            errors += check_ascii(tr, f"EXE {r['Offset']}")
            if len(tr) > len(orig):
                errors.append(f"EXE {r['Offset']}: {len(tr)} caracteres, maximo {len(orig)}")
            if PRINTF.findall(tr) != PRINTF.findall(orig):
                errors.append(f"EXE {r['Offset']}: manter os mesmos {PRINTF.findall(orig)} na mesma ordem")
            if tr.count("/") != orig.count("/"):
                errors.append(f"EXE {r['Offset']}: manter {orig.count('/')} barra(s) '/'")
            raw = tr.encode("ascii", "replace")
            exe[off:off + len(orig)] = raw + b"\x00" * (len(orig) - len(raw))
            changed += 1
        report.append(f"HARVEST.EXE: {changed} textos fixos traduzidos")

    if errors:
        return errors, report, {}

    files = {"DIALOG.RSP": join_crlf(rsp, rsp_tail),
             "DIALOGUE.IDX": xor_aa(join_crlf([x for i, raw in idx for x in (str(i), raw)]))}
    for name, data in scrs:
        lines, tail = split_crlf(xor_aa(data))
        changed = boxes = 0
        for n, kind, ident, box, s, e in sorted(scr_items(lines), key=lambda x: -x[4]):
            orig = scr_to_display(lines[n][s:e])
            new = scr_tr.get((kind, orig))
            if new is not None:
                lines[n] = lines[n][:s] + new + lines[n][e:]
                changed += 1
            if kind == "TEXT" and orig in scr_box and scr_box[orig] != box:
                m = SCR_TEXT.match(lines[n])
                b0, b1 = m.span(3)
                lines[n] = lines[n][:b0] + scr_box[orig] + lines[n][b1:]
                boxes += 1
        files[name] = xor_aa(join_crlf(lines, tail))
        report.append(f"SCR {name}: {changed} textos substituidos, {boxes} caixas trocadas")
    if menu_lines is not None:
        files["MENU.INI"] = join_crlf(menu_lines, menu_tail)
    if exe is not None:
        files["HARVEST.EXE"] = bytes(exe)
    return [], report, files


def print_errors(errors: list[str]) -> int:
    print("ERROS - nada foi gravado:")
    for e in errors:
        print("  " + e)
    return 1


def cmd_construir(a) -> int:
    out: Path = a.saida
    errors, report, files = build_texts(
        a.traducao, a.rsp.read_bytes(), a.idx.read_bytes(), [(p.name, p.read_bytes()) for p in a.scr],
        a.menu.read_bytes() if a.menu else None, a.exe.read_bytes() if a.exe else None)
    if errors:
        return print_errors(errors)
    out.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (out / name).write_bytes(data)
    for line in report:
        print(line)
    for name, data in files.items():
        print(f"  {out / name}  {len(data):,} bytes  SHA-256 {sha256(data)}")
    return 0


def load_image_patches(t: Path) -> dict[str, bytes]:
    """TRADUCAO/IMAGENS: MANIFESTO.csv (sha_original,sha_novo,caminho) + <sha_original>.BM editados."""
    d = t / "IMAGENS"
    out = {}
    if not (d / "MANIFESTO.csv").exists():
        return out
    for line in (d / "MANIFESTO.csv").read_text(encoding="ascii").splitlines():
        if not line.strip():
            continue
        orig, new, _path = line.split(",", 2)
        data = (d / f"{orig}.BM").read_bytes()
        if sha256(data) != new:
            raise ValueError(f"IMAGENS: {orig}.BM nao confere com o manifesto")
        out[orig] = data
    return out


def patch_dat_images(iso_path: Path, patches: dict[str, bytes]) -> int:
    """Substitui no lugar (mesmo tamanho) os registros do HARVEST.DAT cujo conteudo original esta no manifesto."""
    if not patches:
        return 0
    with iso_path.open("r+b") as iso:
        _, extent, size = iso_find_record(iso, "HARVEST.DAT")
        base = extent * SECTOR
        iso.seek(base)
        dat = iso.read(size)
        n = 0
        for m in re.finditer(rb"XFLE.:(\\[^\x00]{1,120})\x00", dat, re.S):
            off = m.start()
            data_off, dsize, _z, dsize2 = struct.unpack_from("<IIII", dat, off + 132)
            if data_off != off + 148 or dsize != dsize2:
                continue
            new = patches.get(sha256(dat[data_off:data_off + dsize]))
            if new is not None and len(new) == dsize:
                iso.seek(base + data_off)
                iso.write(new)
                n += 1
    return n


def iso_read(iso_path: Path, path_in_iso: str) -> bytes:
    with iso_path.open("rb") as iso:
        _, extent, size = iso_find_record(iso, path_in_iso)
        iso.seek(extent * SECTOR)
        return iso.read(size)


def cmd_aplicar(a) -> int:
    """Patch completo: copia HARVEST, traduz RSP/MENU/EXE e grava IDX/SCR em cada ISO."""
    out: Path = a.saida
    if out.exists() and any(out.iterdir()) and not a.force:
        raise FileExistsError(f"{out} ja tem arquivos; use --force")
    isos = sorted(a.isos.glob("*.ISO"))
    if not isos:
        raise FileNotFoundError(f"nenhuma ISO em {a.isos}")
    game: Path = a.jogo

    # valida tudo antes de gravar qualquer coisa
    plans, report = [], []
    for iso in isos:
        errors, rep, files = build_texts(
            a.traducao, (game / "DIALOG.RSP").read_bytes(), iso_read(iso, "DIALOGUE.IDX"),
            [("HARVEST.SCR", iso_read(iso, "HARVEST.SCR"))],
            (game / "MENU.INI").read_bytes(), (game / "HARVEST.EXE").read_bytes())
        if errors:
            return print_errors(errors)
        plans.append((iso, files))
        report.append(f"{iso.name}: " + "; ".join(r for r in rep if r.startswith(("IDX", "SCR"))))
    local = {k: v for k, v in plans[0][1].items() if k in ("DIALOG.RSP", "MENU.INI", "HARVEST.EXE")}
    report = [r for r in rep if not r.startswith(("IDX", "SCR"))] + report

    out.mkdir(parents=True, exist_ok=True)
    if (out / "HARVEST").exists():
        shutil.rmtree(out / "HARVEST")
    shutil.copytree(game, out / "HARVEST")
    for name, data in local.items():
        (out / "HARVEST" / name).write_bytes(data)
    new_isos = []
    patches = load_image_patches(a.traducao)
    for iso, files in plans:
        dst = out / iso.name
        tmp = dst.with_name(dst.name + ".tmp")
        shutil.copyfile(iso, tmp)
        try:
            for inner in ("DIALOGUE.IDX", "HARVEST.SCR"):
                how = iso_replace(tmp, inner, files[inner])
                report.append(f"  {iso.name} {inner}: {how}")
            if patches:
                report.append(f"  {iso.name} HARVEST.DAT: {patch_dat_images(tmp, patches)} imagens traduzidas")
            tmp.replace(dst)
        finally:
            tmp.unlink(missing_ok=True)
        new_isos.append(dst)

    if a.conf_modelo:
        conf = a.conf_modelo.read_text(encoding="ascii")
        conf = re.sub(r'(?im)^mount C .*$', lambda m: f'mount C "{out.resolve()}"', conf)
        conf = re.sub(r'(?im)^imgmount D .*$',
                      lambda m: "imgmount D -t iso " + " ".join(f'"{p.resolve()}"' for p in new_isos), conf)
        (out / "JOGAR.conf").write_text(conf, encoding="ascii")
        report.append(f"  conf: {out / 'JOGAR.conf'}")

    for line in report:
        print(line)
    for p in [out / "HARVEST" / n for n in local] + new_isos:
        print(f"  {p}  {p.stat().st_size:,} bytes")
    return 0


def cmd_status(a) -> int:
    """Cobertura da traducao por planilha."""
    t: Path = a.traducao
    total_t = total_n = 0
    for name, skip in (("TRADUCAO-IDX.csv", None), ("TRADUCAO-RSP.csv", "topicos"),
                       ("TRADUCAO-SCR.csv", None), ("GLOSSARIO-TOPICOS.csv", None),
                       ("TRADUCAO-MENU.csv", None), ("TRADUCAO-EXE.csv", None)):
        p = t / name
        if not p.exists():
            continue
        rows = read_csv(p)
        if skip == "topicos":  # linhas de topico sao cobertas pelo glossario
            rows = [r for r in rows if is_option_line(r["Original"])]
        done = sum(1 for r in rows if r["Traducao"].strip())
        total_t += done
        total_n += len(rows)
        label = name + (" (so opcoes numeradas)" if skip else "")
        print(f"{label:45s} {done:5d}/{len(rows):5d}  {100 * done / max(1, len(rows)):5.1f}%")
    print(f"{'TOTAL':45s} {total_t:5d}/{total_n:5d}  {100 * total_t / max(1, total_n):5.1f}%")
    return 0


def cmd_gravar_iso(a) -> int:
    src: Path = a.iso_original
    dst: Path = a.iso_saida
    if src.resolve() == dst.resolve():
        raise ValueError("a ISO de saida deve ser diferente da original")
    if dst.exists() and not a.force:
        raise FileExistsError(f"{dst} ja existe; use --force")
    if len(a.substituir) % 2:
        raise ValueError("--substituir espera pares: CAMINHO_NA_ISO ARQUIVO_LOCAL")
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".tmp")
    shutil.copyfile(src, tmp)
    try:
        for k in range(0, len(a.substituir), 2):
            inner, local = a.substituir[k], Path(a.substituir[k + 1])
            data = local.read_bytes()
            how = iso_replace(tmp, inner, data, a.sempre_anexar)
            print(f"{inner} <- {local} ({len(data):,} bytes, SHA-256 {sha256(data)}): {how}")
        tmp.replace(dst)
    finally:
        tmp.unlink(missing_ok=True)
    print(f"ISO gravada: {dst} ({dst.stat().st_size:,} bytes)")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("mapear-exe", help="mapa de falas/menus do HARVEST.EXE")
    s.add_argument("--exe", type=Path, required=True)
    s.add_argument("--idx", type=Path, required=True, help="DIALOGUE.IDX cifrado (como no CD)")
    s.add_argument("--rsp", type=Path, required=True)
    s.add_argument("--saida", type=Path, required=True)

    s = sub.add_parser("exportar", help="gera planilhas CSV de traducao")
    s.add_argument("--rsp", type=Path, required=True)
    s.add_argument("--idx", type=Path, required=True, help="DIALOGUE.IDX cifrado")
    s.add_argument("--scr", type=Path, nargs="+", required=True, help="HARVEST.SCR cifrados (variantes)")
    s.add_argument("--mapa", type=Path, help="CSV do mapear-exe (falantes e usos)")
    s.add_argument("--menu", type=Path, help="MENU.INI")
    s.add_argument("--exe", type=Path, help="HARVEST.EXE (textos fixos)")
    s.add_argument("--saida", type=Path, required=True)
    s.add_argument("--force", action="store_true")

    s = sub.add_parser("construir", help="gera arquivos traduzidos a partir das planilhas")
    s.add_argument("--traducao", type=Path, required=True, help="pasta com TRADUCAO-*.csv")
    s.add_argument("--rsp", type=Path, required=True)
    s.add_argument("--idx", type=Path, required=True)
    s.add_argument("--scr", type=Path, nargs="+", required=True)
    s.add_argument("--menu", type=Path)
    s.add_argument("--exe", type=Path)
    s.add_argument("--saida", type=Path, required=True)

    s = sub.add_parser("status", help="cobertura da traducao")
    s.add_argument("--traducao", type=Path, required=True)

    s = sub.add_parser("aplicar", help="patch completo: pasta HARVEST + ISOs + .conf")
    s.add_argument("--traducao", type=Path, required=True)
    s.add_argument("--jogo", type=Path, required=True, help="pasta HARVEST original")
    s.add_argument("--isos", type=Path, required=True, help="pasta com as ISOs originais")
    s.add_argument("--saida", type=Path, required=True)
    s.add_argument("--conf-modelo", type=Path, help="TESTE.conf/dosbox.conf a adaptar (linhas mount C / imgmount D)")
    s.add_argument("--force", action="store_true")

    s = sub.add_parser("gravar-iso", help="copia ISO substituindo arquivos")
    s.add_argument("iso_original", type=Path)
    s.add_argument("iso_saida", type=Path)
    s.add_argument("--substituir", nargs="+", required=True, metavar="ITEM",
                   help="pares CAMINHO_NA_ISO ARQUIVO_LOCAL")
    s.add_argument("--sempre-anexar", action="store_true",
                   help="grava no fim da imagem mesmo que caiba no lugar original")
    s.add_argument("--force", action="store_true")

    a = p.parse_args(argv)
    try:
        return {"mapear-exe": cmd_mapear_exe, "exportar": cmd_exportar, "construir": cmd_construir,
                "gravar-iso": cmd_gravar_iso, "aplicar": cmd_aplicar, "status": cmd_status}[a.cmd](a)
    except (OSError, ValueError, RuntimeError, KeyError) as e:
        print(f"Erro: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
