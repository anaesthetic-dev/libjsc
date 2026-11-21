"""Report SDK binary sizes and enforce the ICU and ELF size checks."""

import argparse
import os
from pathlib import Path
import re
from struct import error as StructError, unpack_from


ICU_LIMIT = 12_000_000


def icu_package(data: bytes, start: int) -> tuple[int, int]:
    # ICU common data offsets are relative to the table of contents.
    header_size, = unpack_from('<H', data, start)
    toc = start + header_size
    count, = unpack_from('<I', data, toc)
    if header_size < 24 or not count or toc + 4 + count * 8 > len(data):
        raise ValueError('Invalid ICU common data table')
    first_name, first_item = unpack_from('<II', data, toc + 4)
    last_name, last_item = unpack_from('<II', data, toc + 4 + (count - 1) * 8)
    if not 4 + count * 8 <= first_name <= last_name < first_item <= last_item:
        raise ValueError('Invalid ICU resource offsets')
    last_name += toc
    last_item += toc
    name_end = data.find(b'\0', last_name, toc + first_item)
    # CmnD records item offsets but no total length. In these ICU data sets
    # the last item is a resource bundle with its own end offset in words.
    if (name_end == -1 or not data[last_name:name_end].endswith(b'.res')
            or data[last_item + 2:last_item + 4] != b'\xda\x27'
            or data[last_item + 12:last_item + 16] != b'ResB'):
        raise ValueError('Cannot determine the length of the final ICU resource bundle')
    item_header_size, = unpack_from('<H', data, last_item)
    indexes, bundle_top = unpack_from('<I8xI', data, last_item + item_header_size + 4)
    if item_header_size < 24 or (indexes & 0xff) < 4 or bundle_top < (indexes & 0xff) + 1:
        raise ValueError('Invalid ICU resource bundle indexes')
    end = last_item + ((item_header_size + 4 * bundle_top + 15) & ~15)
    if end > len(data):
        raise ValueError('ICU common data extends beyond its PE section')
    return end - start, count


def inspect_pe(data: bytes) -> dict:
    pe, = unpack_from('<I', data, 0x3c)
    if data[pe:pe + 4] != b'PE\0\0':
        raise ValueError('Invalid PE signature')
    machine, count = unpack_from('<HH', data, pe + 4)
    if machine != 0x8664:
        raise ValueError('Expected an x64 PE')
    optional_size, = unpack_from('<H', data, pe + 20)
    sections = {}
    for i in range(count):
        offset = pe + 24 + optional_size + 40 * i
        name, virtual_size, _, raw_size, start = unpack_from('<8sIIII', data, offset)
        sections[name.rstrip(b'\0')] = (min(virtual_size, raw_size), start)
    text_size, _ = sections[b'.text']
    rdata_size, start = sections[b'.rdata']
    if start + rdata_size > len(data):
        raise ValueError('Truncated PE .rdata section')
    rdata = data[start:start + rdata_size]
    packages = [match.start() - 2 for match in re.finditer(b'\xda\x27.{8}CmnD', rdata, re.DOTALL)
                if match.start() >= 2 and rdata[match.start() + 6] == 0]  # Little-endian ICU
    if len(packages) != 1:
        raise ValueError(f'Expected one embedded ICU CmnD package, found {len(packages)}')
    icu_size, count = icu_package(rdata, packages[0])
    return {'text_bytes': text_size, 'rdata_bytes': rdata_size,
            'icu_data_bytes': icu_size, 'icu_resources': count}


def has_elf_symtab(data: bytes) -> bool:
    if data[:6] != b'\x7fELF\x02\x01' or unpack_from('<H', data, 18)[0] != 62:
        raise ValueError('Expected a little-endian x64 ELF')
    table, = unpack_from('<Q', data, 40)
    entry_size, count = unpack_from('<HH', data, 58)
    if not table or entry_size < 64:
        raise ValueError('Missing ELF section table')
    if not count:
        count, = unpack_from('<Q', data, table + 32)
    if not count or table + count * entry_size > len(data):
        raise ValueError('Invalid ELF section table')
    # SHT_SYMTAB (2) is the full symbol table. SHT_DYNSYM is needed by consumers.
    return any(unpack_from('<I', data, table + i * entry_size + 4)[0] == 2
               for i in range(count))


def check_size(path: Path) -> dict:
    data = path.read_bytes()
    sizes = {'binary_bytes': len(data)}
    lines = [f'{path.name}: {len(data):,} bytes']
    if data.startswith(b'MZ'):
        sizes.update(inspect_pe(data))
        lines += [
            f".text: {sizes['text_bytes']:,} bytes",
            f".rdata: {sizes['rdata_bytes']:,} bytes",
            f"Embedded ICU: {sizes['icu_data_bytes']:,} bytes, {sizes['icu_resources']:,} resources",
        ]
        failure = (f'Embedded ICU exceeds {ICU_LIMIT:,} bytes'
                   if sizes['icu_data_bytes'] > ICU_LIMIT else None)
    else:
        sizes['has_symtab'] = has_elf_symtab(data)
        lines.append(f".symtab: {'present' if sizes['has_symtab'] else 'absent'}")
        failure = 'ELF still contains .symtab' if sizes['has_symtab'] else None
    print('\n'.join(lines), flush=True)
    if summary := os.environ.get('GITHUB_STEP_SUMMARY'):
        with Path(summary).open('a', encoding='utf-8') as output:
            output.write('\n## SDK binary size\n\n')
            output.writelines(f'- {line}\n' for line in lines)
    if failure:
        raise ValueError(failure)
    return sizes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    args = parser.parse_args()
    try:
        check_size(args.binary)
    except (OSError, ValueError, KeyError, StructError) as error:
        parser.exit(1, f'{args.binary}: {error}\n')


if __name__ == '__main__':
    main()
