#!/usr/bin/env python3
"""Export the text of a GFL2 LangPackage table to UTF-8 JSON for translation.

Python 3.10+; standard library only. Neither script needs to be installed.

Each different text appears once, under a key made from the text itself, so
translations stay matched to their lines when a game update renumbers them.

Double-click this script with LangPackageTableCnData.bytes beside it. The first
run writes translations/base.json. After a game update, put the game's new
LangPackageTableCnData.bytes beside the scripts and run it again: it writes a
file in translations holding only the text that has no translation yet.
Translate the files in translations, then double-click langpackage_import.py.

A translations.json from the earlier version of these scripts, keyed by text
ID, is converted on the first run. That needs the LangPackageTableCnData.bytes
it was exported from.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import sys
import tempfile
from typing import Iterator


ORIGINAL_NAME = "LangPackageTableCnData.bytes"
TRANSLATIONS_DIR = "translations"
LEGACY_FILE = "translations.json"
LEGACY_KEPT_NAME = "translations-old-format.json"
FORMAT = "gfl2-langpackage-by-text-1"
# Files from the ID-keyed scripts: no format field, or the pre-release field value.
LEGACY_FORMATS = (None, "gfl2-langpackage-text-v1")


class TableError(ValueError):
    """Invalid or unsupported input, reported without a traceback by the CLI."""


@dataclass(slots=True)
class Field:
    number: int
    wire: int
    start: int
    payload: int
    end: int
    value: int = 0


def read_varint(data: bytes, pos: int, end: int) -> tuple[int, int]:
    value = 0
    for shift in range(0, 70, 7):
        if pos >= end:
            raise TableError(f"Truncated protobuf varint at byte {pos}.")
        byte = data[pos]
        pos += 1
        if shift == 63 and byte > 1:
            raise TableError(f"Protobuf varint exceeds 64 bits at byte {pos - 1}.")
        value |= (byte & 127) << shift
        if byte < 128:
            return value, pos
    raise TableError("Overlong protobuf varint.")


def varint(value: int) -> bytes:
    if not 0 <= value < 1 << 64:
        raise TableError("Protobuf integer is outside the unsigned 64-bit range.")
    result = bytearray()
    while value >= 128:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def fields(data: bytes, start: int = 0, end: int | None = None) -> Iterator[Field]:
    end = len(data) if end is None else end
    if not 0 <= start <= end <= len(data):
        raise TableError("Protobuf message bounds are outside the file.")
    pos = start
    while pos < end:
        begin = pos
        tag, pos = read_varint(data, pos, end)
        number, wire = tag >> 3, tag & 7
        if not 1 <= number < 1 << 29:
            raise TableError(f"Invalid protobuf field number at byte {begin}.")
        payload, value = pos, 0
        if wire == 0:
            value, pos = read_varint(data, pos, end)
        elif wire == 2:
            length, pos = read_varint(data, pos, end)
            payload = pos
            pos += length
        elif wire in (1, 5):
            pos += 8 if wire == 1 else 4
        else:
            raise TableError(f"Unsupported protobuf wire type {wire} at byte {begin}.")
        if pos > end:
            raise TableError(f"Protobuf field at byte {begin} extends beyond its message.")
        yield Field(number, wire, begin, payload, pos, value)


def single(items: list[Field], number: int, wire: int, *, optional: bool = False) -> Field | None:
    matches = [f for f in items if f.number == number]
    if not matches and optional:
        return None
    if len(matches) != 1 or matches[0].wire != wire:
        raise TableError(f"Expected one field #{number} with wire type {wire}.")
    return matches[0]


@dataclass(slots=True)
class Row:
    id: int
    text: str
    field: Field


@dataclass(slots=True)
class Index:
    field: Field
    value_field: Field
    offset: int
    length: int


@dataclass(slots=True)
class Table:
    data: bytes
    body_start: int
    metadata: list[Field]
    indexes: list[Index]
    rows: list[Row]

def load_table(path: Path) -> Table:
    data = path.read_bytes()
    if len(data) < 4:
        raise TableError("The table is shorter than its four-byte header.")
    body_start = 4 + struct.unpack_from("<I", data)[0]
    if body_start > len(data):
        raise TableError("The table header points beyond the end of the file.")
    metadata = list(fields(data, 4, body_start))
    rows, ids, boundaries = [], set(), {0}
    for outer in fields(data, body_start):
        if (outer.number, outer.wire) != (1, 2):
            raise TableError("The row section contains an unsupported non-row field.")
        inner = list(fields(data, outer.payload, outer.end))
        identity = single(inner, 1, 0)
        text = single(inner, 2, 2, optional=True)
        assert identity is not None
        if identity.value in ids:
            raise TableError(f"Duplicate text ID {identity.value} in the source table.")
        ids.add(identity.value)
        try:
            value = data[text.payload:text.end].decode("utf-8") if text else ""
        except UnicodeDecodeError as exc:
            raise TableError(f"Text ID {identity.value} is not valid UTF-8.") from exc
        rows.append(Row(identity.value, value, outer))
        boundaries.add(outer.end - body_start)

    indexes = []
    for outer in metadata:
        if outer.number == 1 and outer.wire == 2:
            raise TableError("The header includes rows instead of only table metadata.")
        if outer.number != 3:
            continue
        if outer.wire != 2:
            raise TableError("Unsupported table index encoding.")
        inner = list(fields(data, outer.payload, outer.end))
        single(inner, 1, 0, optional=True)  # Index key: preserve, including omitted zero.
        value = single(inner, 2, 2)
        assert value is not None
        parts = list(fields(data, value.payload, value.end))
        offset = single(parts, 1, 0, optional=True)
        length = single(parts, 2, 0)
        assert length is not None
        start, size = offset.value if offset else 0, length.value
        if size == 0 or start not in boundaries or start + size not in boundaries:
            raise TableError("An index range does not align with complete rows.")
        indexes.append(Index(outer, value, start, size))
    # Require complete, non-overlapping coverage; do not guess at an unknown index layout.
    cursor = 0
    for index in sorted(indexes, key=lambda item: item.offset):
        if index.offset != cursor:
            raise TableError("The table index has a gap or overlapping ranges.")
        cursor += index.length
    if cursor != len(data) - body_start:
        raise TableError("The index does not cover the complete row section.")
    return Table(data, body_start, metadata, indexes, rows)


def fingerprint(text: str) -> str:
    """Translation key for a text: the first 64 bits of its UTF-8 SHA-256, in hex."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


KEY = re.compile(r"[0-9a-f]{16}")


def source_texts(table: Table) -> dict[str, str]:
    """Key -> text for every non-empty text in the table, ordered by its lowest ID."""
    texts: dict[str, str] = {}
    for row in sorted(table.rows, key=lambda item: item.id):
        if not row.text:
            continue  # Empty lines have nothing to translate.
        key = fingerprint(row.text)
        if texts.setdefault(key, row.text) != row.text:
            raise TableError(f"Two different texts share the translation key {key}; these scripts cannot tell them apart.")
    return texts


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise TableError(f"Duplicate JSON key {key!r}.")
        result[key] = value
    return result


def json_files(path: Path) -> list[Path]:
    files = sorted(path.glob("*.json")) if path.is_dir() else [path]
    if not files:
        raise TableError(f"{path.name} contains no .json files.")
    return files


def read_documents(path: Path) -> Iterator[tuple[Path, object, dict]]:
    """(file, format, texts) for each JSON file, with every text checked to be a string."""
    for file in json_files(path):
        try:
            document = json.loads(file.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_object)
            if not isinstance(document, dict):
                raise TableError("Expected a JSON object containing texts.")
            texts = document.get("texts")
            if not isinstance(texts, dict):
                raise TableError("The texts property must be an object mapping keys to strings.")
            for key, text in texts.items():
                if not isinstance(text, str):
                    raise TableError(f"Key {key} must contain a string (empty strings are allowed).")
                try:
                    text.encode("utf-8")
                except UnicodeEncodeError as exc:
                    raise TableError(f"Key {key} contains an invalid Unicode surrogate.") from exc
        except (ValueError, UnicodeError) as exc:
            raise TableError(f"{file.name}: {exc}") from exc
        yield file, document.get("format"), texts


def read_translations(path: Path) -> dict[str, str]:
    """Translation key -> translated text, from one file or every .json file in a folder."""
    translations: dict[str, str] = {}
    origin: dict[str, str] = {}
    for file, format_name, texts in read_documents(path):
        if format_name in LEGACY_FORMATS:
            raise TableError(
                f"{file.name} is keyed by text ID, from the earlier version of these scripts. "
                "Convert it with langpackage_export.py first."
            )
        if format_name != FORMAT:
            raise TableError(f"{file.name} is not a translation file these scripts recognise.")
        for key, text in texts.items():
            if not KEY.fullmatch(key):
                raise TableError(f"{file.name}: malformed translation key {key!r}.")
            if key in translations:
                raise TableError(f"Translation key {key} is in both {origin[key]} and {file.name}.")
            translations[key] = text
            origin[key] = file.name
    return translations


def read_legacy(path: Path) -> dict[int, str]:
    """Line ID -> translated text, from a file written by the ID-keyed scripts."""
    translations: dict[int, str] = {}
    for file, format_name, texts in read_documents(path):
        if format_name not in LEGACY_FORMATS:
            raise TableError(f"{file.name} is not a translation file from the earlier version of these scripts.")
        for key, text in texts.items():
            if not re.fullmatch(r"0|[1-9][0-9]{0,19}", key):
                raise TableError(f"{file.name}: malformed text ID {key!r}.")
            if int(key) in translations:
                raise TableError(f"Text ID {key} occurs in more than one file.")
            translations[int(key)] = text
    return translations


@dataclass(slots=True)
class Conversion:
    texts: dict[str, str]
    lines: int
    conflicts: int


def convert_legacy(table: Table, legacy: dict[int, str]) -> Conversion:
    """Re-key ID-keyed translations by text, using the table they were exported from."""
    sources = {row.id: row.text for row in table.rows}
    if legacy.keys() != sources.keys():
        raise TableError("The text IDs in the translation do not match this game file, so it was not exported from this file.")
    choices: dict[str, Counter[str]] = {}
    for identity in sorted(legacy):
        source = sources[identity]
        if source:
            choices.setdefault(fingerprint(source), Counter())[legacy[identity]] += 1
    texts, conflicts = {}, 0
    for key, source in source_texts(table).items():
        counts = choices[key]
        translated = [text for text in counts if text != source]
        conflicts += len(translated) > 1
        # A translated line beats an untranslated copy; then the most common wins; ties go to the lowest ID.
        texts[key] = max(translated or counts, key=lambda text: counts[text])
    return Conversion(texts, len(legacy), conflicts)


def write_document(path: Path, texts: dict[str, str]) -> None:
    """Write a translation file that must not exist yet; a failed write leaves no file behind."""
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite {path}")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="\n", dir=path.parent, prefix=".langpackage-", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump({"format": FORMAT, "texts": texts}, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def export_table(
    source: Path, destination: Path, chunk_size: int | None = None, translated: Path | None = None,
) -> tuple[int, int]:
    """Write the table's texts, skipping keys already in `translated`. Returns (texts, files)."""
    if chunk_size is not None and chunk_size < 1:
        raise TableError("Chunk size must be at least 1.")
    if destination.exists():
        raise FileExistsError(f"The export destination already exists: {destination}")
    known = read_translations(translated) if translated is not None else {}
    texts = [(key, text) for key, text in source_texts(load_table(source)).items() if key not in known]
    size = chunk_size if chunk_size is not None else max(1, len(texts))
    count = max(1, (len(texts) + size - 1) // size)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if chunk_size is not None:
        destination.mkdir()
    for part in range(count):
        path = destination if chunk_size is None else destination / f"{part + 1:04d}.json"
        write_document(path, dict(texts[part * size:(part + 1) * size]))
    return len(texts), count


def nearby_original(directory: Path) -> Path:
    source = directory / ORIGINAL_NAME
    if not source.is_file():
        raise TableError(
            f"Place the game's {ORIGINAL_NAME} file beside both scripts, then run this script again.\n"
            f"Folder: {directory}"
        )
    return source


def has_translations(folder: Path) -> bool:
    return folder.is_dir() and any(folder.glob("*.json"))


def wait_to_close() -> None:
    # Explorer launches a temporary console for .py files. Keep results and errors visible.
    try:
        input("\nPress Enter to close...")
    except (EOFError, KeyboardInterrupt):
        pass


def convert_nearby(directory: Path, table: Table, folder: Path) -> None:
    legacy_path = directory / LEGACY_FILE
    kept = directory / LEGACY_KEPT_NAME
    if kept.exists():
        raise TableError(f"Move or rename {LEGACY_KEPT_NAME} first; converting keeps translations.json under that name.")
    print("Converting translations.json to translations that follow their text...", flush=True)
    try:
        conversion = convert_legacy(table, read_legacy(legacy_path))
    except TableError as exc:
        raise TableError(
            f"{exc}\nPut the {ORIGINAL_NAME} that translations.json was exported from beside the scripts, "
            "run this again, and only then replace it with the game's new file."
        ) from exc
    folder.mkdir(exist_ok=True)
    write_document(folder / "base.json", conversion.texts)
    legacy_path.rename(kept)
    print(f"Converted {conversion.lines:,} lines into {len(conversion.texts):,} texts in {TRANSLATIONS_DIR}\\base.json.")
    if conversion.conflicts:
        print(f"{conversion.conflicts:,} texts were translated differently on different lines; each keeps its most common translation.")
    print(f"The old file is kept as {LEGACY_KEPT_NAME}; nothing reads it any more.\n")


def next_update_name(folder: Path) -> str:
    number = 1
    while (folder / f"update-{number:03d}.json").exists():
        number += 1
    return f"update-{number:03d}.json"


def double_click_setup() -> int:
    directory = Path(__file__).resolve().parent
    folder = directory / TRANSLATIONS_DIR
    print("Set up text for translation\n", flush=True)
    try:
        source = nearby_original(directory)
        print(f"Reading {source.name}...", flush=True)
        table = load_table(source)
        if not has_translations(folder) and (directory / LEGACY_FILE).is_file():
            convert_nearby(directory, table, folder)
        elif (directory / LEGACY_FILE).is_file():
            print(f"translations.json is in the earlier format and is not used; your translations are in {TRANSLATIONS_DIR}.\n")
        known = read_translations(folder) if has_translations(folder) else {}
        new = {key: text for key, text in source_texts(table).items() if key not in known}
        if not new:
            print("Every text in this game file already has an entry in translations.")
            print("Double-click langpackage_import.py to create the translated file.")
            return 0
        folder.mkdir(exist_ok=True)
        name = next_update_name(folder) if known else "base.json"
        write_document(folder / name, new)
        print(f"Ready: {len(new):,} texts to translate in {TRANSLATIONS_DIR}\\{name}")
        print("Translate only the text values. Leave the keys and the format line as they are.")
        print("When ready, double-click langpackage_import.py to create the translated file.")
        print(f"After a game update, put the game's new {ORIGINAL_NAME} here and run this script again.")
        return 0
    except (OSError, ValueError) as exc:
        print(f"\nSetup could not finish: {exc}")
        return 1
    finally:
        wait_to_close()


def main() -> int:
    if len(sys.argv) == 1:
        return double_click_setup()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", type=Path, help="The game's LangPackageTableCnData.bytes (or another locale).")
    parser.add_argument("output", type=Path, help="New JSON output file; must not exist.")
    parser.add_argument("--chunk-size", type=int, help="Split the export; output is then a new folder of numbered files.")
    parser.add_argument("--skip-translated", type=Path, metavar="TRANSLATIONS", help="Leave out texts already in this translation file or folder.")
    parser.add_argument("--convert", type=Path, metavar="OLD_JSON", help="Convert an ID-keyed translation exported from SOURCE instead of exporting.")
    args = parser.parse_args()
    try:
        if args.convert is not None:
            if args.output.exists():
                raise FileExistsError(f"The output already exists: {args.output}")
            conversion = convert_legacy(load_table(args.source), read_legacy(args.convert))
            args.output.parent.mkdir(parents=True, exist_ok=True)
            write_document(args.output, conversion.texts)
            print(f"Converted {conversion.lines:,} lines into {len(conversion.texts):,} texts: {args.output.resolve()}")
            print(f"{conversion.conflicts:,} texts had differing translations; each keeps its most common one.")
            return 0
        entries, batches = export_table(args.source, args.output, args.chunk_size, args.skip_translated)
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Exported {entries:,} texts to {batches:,} UTF-8 JSON file(s): {args.output.resolve()}")
    print("Translate only the text values. Leave the keys and the format line as they are.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
