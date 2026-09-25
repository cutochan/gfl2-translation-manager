#!/usr/bin/env python3
"""Rebuild a GFL2 LangPackage table from translated JSON.

Python 3.10+; standard library only. Keep langpackage_export.py alongside this
script. Each line takes the translation of its text, wherever the line sits in
this version of the game. Lines whose text has no translation keep it as it is.

Double-click this script after translating the files in the translations folder.
It reads the game's LangPackageTableCnData.bytes beside the scripts and writes
output/LangPackageTableCnData.bytes. Running it again refreshes that output.
Optional command-line use requires a new output file.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import struct
import sys
import tempfile

from .langpackage_export import (
    LEGACY_FILE, ORIGINAL_NAME, TRANSLATIONS_DIR, Table, TableError, fields, fingerprint,
    has_translations, load_table, nearby_original, read_translations, source_texts, varint, wait_to_close,
)


def length_field(number: int, payload: bytes) -> bytes:
    return varint((number << 3) | 2) + varint(len(payload)) + payload


def replace_numbers(data: bytes, start: int, end: int, replacements: dict[int, int]) -> bytes:
    result, seen = [], set()
    for field in fields(data, start, end):
        if field.number in replacements:
            value = replacements[field.number]
            seen.add(field.number)
            # Preserve the original bytes when the value did not change.
            result.append(data[field.start:field.end] if value == field.value else varint(field.number << 3) + varint(value))
        else:
            result.append(data[field.start:field.end])
    for number, value in replacements.items():
        if number not in seen and value:
            result.append(varint(number << 3) + varint(value))
    return b"".join(result)


def rebuild(table: Table, translations: dict[int, str]) -> tuple[bytes, int]:
    data = table.data
    segments, offsets = [], {0: 0}
    position, changed = 0, 0
    for row in table.rows:
        outer = row.field
        text = translations.get(row.id, row.text)
        if text == row.text:
            segment = data[outer.start:outer.end]
        else:
            encoded = text.encode("utf-8")
            inner, replaced = [], False
            for field in fields(data, outer.payload, outer.end):
                if field.number == 2:
                    inner.append(length_field(2, encoded))
                    replaced = True
                else:
                    inner.append(data[field.start:field.end])
            if not replaced:
                inner.append(length_field(2, encoded))
            segment = length_field(1, b"".join(inner))
            changed += 1
        segments.append(segment)
        position += len(segment)
        offsets[outer.end - table.body_start] = position

    index_replacements = {}
    for index in table.indexes:
        start = offsets[index.offset]
        end = offsets[index.offset + index.length]
        if start == index.offset and end - start == index.length:
            continue
        value = index.value_field
        rewritten = replace_numbers(data, value.payload, value.end, {1: start, 2: end - start})
        inner = []
        for field in fields(data, index.field.payload, index.field.end):
            inner.append(length_field(2, rewritten) if field.start == value.start else data[field.start:field.end])
        index_replacements[index.field.start] = length_field(3, b"".join(inner))
    metadata = b"".join(index_replacements.get(f.start, data[f.start:f.end]) for f in table.metadata)
    if len(metadata) >= 1 << 32:
        raise TableError("Rebuilt index is too large for the four-byte header.")
    return struct.pack("<I", len(metadata)) + metadata + b"".join(segments), changed


def import_table(
    source: Path, translations: Path, output: Path,
    *, refresh_output: bool = False,
) -> tuple[int, int, int, int, int]:
    """Returns (lines, lines with an entry, lines changed, lines without an entry, entries this table does not use)."""
    if source.resolve() == output.resolve() or (output.exists() and not refresh_output):
        raise TableError("Output must be a new file; the original and existing outputs are never overwritten.")
    table = load_table(source)
    texts = source_texts(table)  # Also refuses two texts that share a key.
    edits = read_translations(translations)
    by_id = {}
    for row in table.rows:
        key = fingerprint(row.text) if row.text else None
        if key in edits:
            by_id[row.id] = edits[key]
    missing = sum(1 for row in table.rows if row.text and row.id not in by_id)
    result, changed = rebuild(table, by_id)
    output.parent.mkdir(parents=True, exist_ok=True)
    if refresh_output:
        # Finish writing before refreshing the generated output, retaining it if a write fails.
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=output.parent, prefix=".langpackage-", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(result)
            os.replace(temporary, output)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    else:
        # Exclusive creation protects explicit CLI output paths from concurrent writes.
        with output.open("xb") as stream:
            stream.write(result)
    unused = len(edits.keys() - texts.keys())
    return len(table.rows), len(by_id), changed, missing, unused


def double_click_import() -> int:
    directory = Path(__file__).resolve().parent
    print("Create the translated table\n", flush=True)
    try:
        source = nearby_original(directory)
        folder = directory / TRANSLATIONS_DIR
        if not has_translations(folder):
            if (directory / LEGACY_FILE).is_file():
                raise TableError("translations.json is in the earlier format. Double-click langpackage_export.py to convert it, then run this again.")
            raise TableError("Run langpackage_export.py first, then translate the files in the translations folder.")
        output = directory / "output" / ORIGINAL_NAME
        print("Reading translations and rebuilding the table...", flush=True)
        total, translated, changed, missing, unused = import_table(source, folder, output, refresh_output=True)
        print(f"\nReady: {output}")
        print(f"{changed:,} of {total:,} lines changed.")
        if missing:
            print(f"{missing:,} lines have text with no translation yet and stay as they are.")
            print("If the game has updated, double-click langpackage_export.py to get that text for translation.")
        if unused:
            print(f"{unused:,} translations are for text no longer in this game file; they stay in your files unused.")
        print("Your game file beside the scripts is untouched.")
        print("After more translation edits, run this script again to refresh the file in output.")
        return 0
    except (OSError, ValueError) as exc:
        print(f"\nNo output was created or refreshed: {exc}")
        return 1
    finally:
        wait_to_close()


def main() -> int:
    if len(sys.argv) == 1:
        return double_click_import()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", type=Path, help="The game's .bytes file to translate.")
    parser.add_argument("translations", type=Path, help="One translation file, or a folder of them.")
    parser.add_argument("output", type=Path, help="New .bytes output file; existing files are never overwritten.")
    args = parser.parse_args()
    try:
        total, translated, changed, missing, unused = import_table(args.source, args.translations, args.output)
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {args.output.resolve()}")
    print(f"{total:,} lines; {translated:,} with a translation entry; {changed:,} changed; {missing:,} without one; "
          f"{unused:,} entries unused by this table.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
