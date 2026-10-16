#!/usr/bin/env python3
"""Inspect, unpack, and round-trip XFLE resource containers."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO


MANIFEST_NAME = "xfle_manifest.json"
MANIFEST_VERSION = 1
PATH_PATTERN = re.compile(rb"\\[A-Za-z0-9_ .\\-]+\.[A-Za-z0-9]{1,5}\Z")


@dataclass(frozen=True)
class Entry:
    marker_offset: int
    slot: int
    internal_path: str
    payload_offset: int
    payload_size: int


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_entries(data: bytes) -> list[Entry]:
    entries: list[Entry] = []
    search_from = 0

    while True:
        marker_offset = data.find(b"XFLE", search_from)
        if marker_offset < 0:
            break
        search_from = marker_offset + 4

        if marker_offset + 6 > len(data):
            continue
        slot_byte, colon = data[marker_offset + 4 : marker_offset + 6]
        if not (ord("0") <= slot_byte <= ord("9")) or colon != ord(":"):
            continue

        path_start = marker_offset + 6
        path_end = data.find(b"\0", path_start, min(len(data), path_start + 258))
        if path_end < 0:
            continue

        raw_path = data[path_start:path_end]
        if not PATH_PATTERN.fullmatch(raw_path):
            continue
        try:
            internal_path = raw_path.decode("ascii")
        except UnicodeDecodeError:
            continue

        path_parts = PurePosixPath(internal_path[1:].replace("\\", "/")).parts
        if not path_parts or any(part in {"", ".", ".."} for part in path_parts):
            continue

        entries.append(
            Entry(
                marker_offset=marker_offset,
                slot=slot_byte - ord("0"),
                internal_path=internal_path,
                payload_offset=path_end + 1,
                payload_size=0,
            )
        )

    if not entries:
        raise ValueError("Nenhum marcador XFLE com caminho valido foi encontrado.")

    bounded_entries: list[Entry] = []
    for index, entry in enumerate(entries):
        end = entries[index + 1].marker_offset if index + 1 < len(entries) else len(data)
        if end < entry.payload_offset:
            raise ValueError(
                f"Marcadores XFLE sobrepostos no offset 0x{entry.marker_offset:X}."
            )
        bounded_entries.append(
            Entry(
                marker_offset=entry.marker_offset,
                slot=entry.slot,
                internal_path=entry.internal_path,
                payload_offset=entry.payload_offset,
                payload_size=end - entry.payload_offset,
            )
        )

    return bounded_entries


def safe_output_path(root: Path, relative_path: str) -> Path:
    candidate = (root / Path(*PurePosixPath(relative_path).parts)).resolve()
    resolved_root = root.resolve()
    if candidate == resolved_root or resolved_root not in candidate.parents:
        raise ValueError(f"Caminho de saida inseguro no manifesto: {relative_path}")
    return candidate


def relative_resource_path(slot: int, internal_path: str) -> str:
    path = PurePosixPath(internal_path[1:].replace("\\", "/"))
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"Caminho interno inseguro no contenedor: {internal_path}")
    return str(PurePosixPath("resources") / f"XFLE{slot}" / path)


def iter_iso_directory(
    stream: BinaryIO, extent: int, size: int
) -> list[tuple[str, int, int, int]]:
    stream.seek(extent * 2048)
    data = stream.read(size)
    entries: list[tuple[str, int, int, int]] = []
    position = 0
    while position < len(data):
        record_length = data[position]
        if record_length == 0:
            position = ((position // 2048) + 1) * 2048
            continue
        record = data[position : position + record_length]
        if len(record) != record_length or record_length < 34:
            raise ValueError("Registro ISO9660 invalido.")
        name_length = record[32]
        raw_name = record[33 : 33 + name_length]
        if len(raw_name) != name_length:
            raise ValueError("Nome ISO9660 truncado.")
        if raw_name not in (b"\0", b"\1"):
            name = raw_name.decode("ascii").split(";", 1)[0].rstrip(".")
            entries.append(
                (
                    name,
                    int.from_bytes(record[2:6], "little"),
                    int.from_bytes(record[10:14], "little"),
                    record[25],
                )
            )
        position += record_length
    return entries


def find_iso_entry(iso_path: Path, internal_path: str) -> tuple[int, int]:
    relative_path = PurePosixPath(internal_path.replace("\\", "/"))
    parts = relative_path.parts
    if relative_path.is_absolute() or not parts or any(
        part in {"", ".", ".."} for part in parts
    ):
        raise ValueError(f"Caminho ISO invalido: {internal_path}")

    with iso_path.open("rb") as stream:
        stream.seek(16 * 2048)
        descriptor = stream.read(2048)
        if (
            len(descriptor) != 2048
            or descriptor[0] != 1
            or descriptor[1:6] != b"CD001"
            or descriptor[6] != 1
        ):
            raise ValueError(f"Nao foi encontrado um descritor ISO9660 valido: {iso_path}")

        root_record = descriptor[156:190]
        if len(root_record) < 34 or root_record[0] < 34:
            raise ValueError("Registro ISO9660 do diretorio raiz invalido.")
        current_extent = int.from_bytes(root_record[2:6], "little")
        current_size = int.from_bytes(root_record[10:14], "little")

        for index, part in enumerate(parts):
            matches = [
                entry
                for entry in iter_iso_directory(stream, current_extent, current_size)
                if entry[0].casefold() == part.casefold()
            ]
            if len(matches) != 1:
                raise FileNotFoundError(
                    f"Esperada uma entrada ISO para '{part}', encontradas: {len(matches)}."
                )
            _, current_extent, current_size, flags = matches[0]
            is_directory = (flags & 2) != 0
            is_final = index == len(parts) - 1
            if is_final and is_directory:
                raise IsADirectoryError(f"A entrada ISO e uma pasta: {internal_path}")
            if not is_final and not is_directory:
                raise NotADirectoryError(f"Componente ISO nao e uma pasta: {part}")
            if flags & 0x80:
                raise ValueError(f"Arquivo ISO de multiplas extensoes nao suportado: {part}")

        if current_extent * 2048 + current_size > iso_path.stat().st_size:
            raise ValueError(f"Entrada ISO ultrapassa o tamanho da imagem: {internal_path}")
        return current_extent * 2048, current_size


def extract_iso_entry(iso_path: Path, internal_path: str, output_path: Path, force: bool) -> int:
    offset, size = find_iso_entry(iso_path, internal_path)
    if output_path.exists() and not force:
        raise FileExistsError(f"O arquivo de saida ja existe: {output_path}; use --force.")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            with iso_path.open("rb") as source:
                source.seek(offset)
                remaining = size
                while remaining:
                    block = source.read(min(1024 * 1024, remaining))
                    if not block:
                        raise OSError(f"Leitura incompleta da entrada ISO: {internal_path}")
                    temporary.write(block)
                    remaining -= len(block)
        os.replace(temporary_path, output_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    print(f"Entrada extraida: {internal_path}")
    print(f"Tamanho: {output_path.stat().st_size:,} bytes")
    print(f"SHA-256: {sha256_file(output_path)}")
    print(f"Arquivo: {output_path}")
    return 0


def inspect_container(container_path: Path, show_all: bool) -> int:
    data = container_path.read_bytes()
    entries = parse_entries(data)
    print(f"Contenedor: {container_path}")
    print(f"Tamanho: {len(data):,} bytes")
    print(f"SHA-256: {hashlib.sha256(data).hexdigest()}")
    print(f"Registros XFLE reconhecidos: {len(entries)}")
    print(f"Bytes antes do primeiro registro: {entries[0].marker_offset}")

    display_entries = entries if show_all else entries[:20]
    for entry in display_entries:
        print(
            f"0x{entry.marker_offset:08X}  XFLE{entry.slot}  "
            f"{entry.internal_path}  payload={entry.payload_size:,} bytes"
        )
    if not show_all and len(entries) > len(display_entries):
        print(f"... {len(entries) - len(display_entries)} registros omitidos; use --all.")
    return 0


def unpack_container(container_path: Path, output_dir: Path) -> int:
    if output_dir.exists():
        raise FileExistsError(
            f"A pasta de saida ja existe; escolha outra para evitar sobrescrever: {output_dir}"
        )

    data = container_path.read_bytes()
    entries = parse_entries(data)
    output_dir.mkdir(parents=True)
    manifest_entries: list[dict[str, object]] = []
    targets: set[str] = set()

    for index, entry in enumerate(entries):
        relative_path = relative_resource_path(entry.slot, entry.internal_path)
        storage_path = PurePosixPath(relative_path)
        candidate = relative_path
        suffix_index = 0
        while candidate.casefold() in targets:
            suffix_index += 1
            duplicate_tag = f".__xfle_record_{index:04d}"
            if suffix_index > 1:
                duplicate_tag += f"_{suffix_index}"
            candidate = str(
                storage_path.with_name(
                    f"{storage_path.stem}{duplicate_tag}{storage_path.suffix}"
                )
            )
        relative_path = candidate
        targets.add(relative_path.casefold())

        target = safe_output_path(output_dir, relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload_end = entry.payload_offset + entry.payload_size
        target.write_bytes(data[entry.payload_offset:payload_end])
        manifest_entries.append(
            {
                **asdict(entry),
                "relative_path": relative_path,
                "prefix_hex": data[entry.marker_offset:entry.payload_offset].hex(),
            }
        )

    manifest = {
        "format": "XFLE sequential-marker inventory; payload extends to the next valid XFLE marker",
        "manifest_version": MANIFEST_VERSION,
        "source_name": container_path.name,
        "source_size": len(data),
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "leading_bytes_hex": data[: entries[0].marker_offset].hex(),
        "records": manifest_entries,
    }
    (output_dir / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Registros extraidos: {len(entries)}")
    print(f"Pasta de recursos: {output_dir}")
    print(f"Manifesto: {output_dir / MANIFEST_NAME}")
    print("Os payloads sao fatias entre marcadores; a estrutura interna nao foi decodificada.")
    return 0


def pack_container(input_dir: Path, output_path: Path, force: bool) -> int:
    manifest_path = input_dir / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("O manifesto deve ser um objeto JSON.")
    if manifest.get("manifest_version") != MANIFEST_VERSION:
        raise ValueError("Versao de manifesto XFLE nao suportada.")

    records = manifest.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("O manifesto nao contem registros XFLE.")
    if output_path.exists() and not force:
        raise FileExistsError(f"O arquivo de saida ja existe: {output_path}; use --force.")

    previous_marker = -1
    original_size = manifest.get("source_size")
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError(f"Registro {index} do manifesto nao e um objeto.")
        marker_offset = record.get("marker_offset")
        payload_offset = record.get("payload_offset")
        payload_size = record.get("payload_size")
        slot = record.get("slot")
        internal_path = record.get("internal_path")
        prefix_hex = record.get("prefix_hex")
        if (
            not isinstance(marker_offset, int)
            or not isinstance(payload_offset, int)
            or not isinstance(payload_size, int)
            or not isinstance(slot, int)
            or not isinstance(internal_path, str)
            or not isinstance(prefix_hex, str)
            or marker_offset <= previous_marker
            or payload_size < 0
        ):
            raise ValueError(f"Metadados invalidos no registro {index} do manifesto.")
        prefix = bytes.fromhex(prefix_hex)
        expected_prefix = f"XFLE{slot}:{internal_path}".encode("ascii") + b"\0"
        if prefix != expected_prefix or payload_offset != marker_offset + len(prefix):
            raise ValueError(f"Cabecalho inconsistente no registro {index} do manifesto.")
        end = marker_offset + len(prefix) + payload_size
        expected_end = (
            records[index + 1].get("marker_offset")
            if index + 1 < len(records) and isinstance(records[index + 1], dict)
            else original_size
        )
        if not isinstance(expected_end, int) or end != expected_end:
            raise ValueError(f"Limites inconsistentes no registro {index} do manifesto.")
        previous_marker = marker_offset

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=output_path.parent, prefix=f".{output_path.name}.", suffix=".tmp", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(bytes.fromhex(manifest.get("leading_bytes_hex", "")))
            for record in records:
                relative_path = record.get("relative_path")
                prefix_hex = record.get("prefix_hex")
                if not isinstance(relative_path, str) or not isinstance(prefix_hex, str):
                    raise ValueError("Registro XFLE invalido no manifesto.")
                source = safe_output_path(input_dir, relative_path)
                if not source.is_file():
                    raise FileNotFoundError(f"Recurso extraido nao encontrado: {source}")
                temporary.write(bytes.fromhex(prefix_hex))
                with source.open("rb") as payload:
                    for block in iter(lambda: payload.read(1024 * 1024), b""):
                        temporary.write(block)

        os.replace(temporary_path, output_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    output_hash = sha256_file(output_path)
    original_hash = manifest.get("source_sha256")
    print(f"Contenedor gravado: {output_path}")
    print(f"Tamanho final: {output_path.stat().st_size:,} bytes")
    print(f"SHA-256 final: {output_hash}")
    if output_hash == original_hash:
        print("Round-trip identico: o arquivo reconstruido corresponde byte a byte ao original.")
    else:
        print("Conteudo diferente do original; recursos alterados nao foram validados pelo jogo.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspeciona e desempacota contenedores XFLE com marcadores sequenciais."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="lista marcadores, caminhos e tamanhos de fatias")
    inspect_parser.add_argument("container", type=Path)
    inspect_parser.add_argument("--all", action="store_true", help="mostra todos os registros")

    unpack_parser = subparsers.add_parser("unpack", help="extrai fatias e cria manifesto para round-trip")
    unpack_parser.add_argument("container", type=Path)
    unpack_parser.add_argument("output_dir", type=Path)

    iso_parser = subparsers.add_parser("extract-iso", help="copia um arquivo da ISO sem extrair o disco inteiro")
    iso_parser.add_argument("iso", type=Path)
    iso_parser.add_argument("iso_path", help="caminho dentro da ISO, por exemplo HARVEST.DAT")
    iso_parser.add_argument("output", type=Path)
    iso_parser.add_argument("--force", action="store_true", help="permite substituir o arquivo de saida")

    pack_parser = subparsers.add_parser("pack", help="reconstroi o contenedor a partir do manifesto")
    pack_parser.add_argument("input_dir", type=Path)
    pack_parser.add_argument("output", type=Path)
    pack_parser.add_argument("--force", action="store_true", help="permite substituir o arquivo de saida")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            return inspect_container(args.container, args.all)
        if args.command == "unpack":
            return unpack_container(args.container, args.output_dir)
        if args.command == "extract-iso":
            return extract_iso_entry(args.iso, args.iso_path, args.output, args.force)
        if args.command == "pack":
            return pack_container(args.input_dir, args.output, args.force)
        parser.error("Comando desconhecido.")
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Erro: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
