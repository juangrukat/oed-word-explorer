"""Bounded static decoding probe, not a production importer.

Algorithm reference: https://9p.io/sources/contrib/tristan/oed/decompress.c
This implementation validates boundaries and reports sample coverage explicitly.
"""
import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

BLOCK = 32768


def decode(raw):
    b = bytearray(raw)
    number, unknown, dictionary_size, symbol_count = struct.unpack_from('>4I', b)
    table = 16 + dictionary_size
    if not (16 < table < BLOCK - 384 and 0 < symbol_count < BLOCK):
        raise ValueError('Invalid block header')
    symbols = []
    cursor = 16
    for _ in range(symbol_count):
        start = cursor
        while cursor < table and not b[cursor] & 128:
            cursor += 1
        if cursor >= table:
            raise ValueError('Unterminated dictionary symbol')
        b[cursor] &= 127
        cursor += 1
        symbols.append(bytes(b[start:cursor]))
    count = struct.unpack_from('>I', b, table)[0]
    if not 1 < count < 32:
        raise ValueError('Invalid code table size')
    values = struct.unpack_from('>' + str(count + 1) + 'I', b, table)
    ranges = [(0, 0, 0)]
    for j in range(1, count):
        lower = ranges[-1][1] * 2
        ranges.append((lower, lower + values[j + 1], ranges[-1][2] + values[j]))
    output = bytearray()
    code = depth = zeros = 0
    for byte in b[table + 384:]:
        for bit in range(7, -1, -1):
            code = code * 2 + ((byte >> bit) & 1)
            if depth >= len(ranges):
                raise ValueError('Invalid prefix code')
            lower, upper, base = ranges[depth]
            if lower <= code < upper:
                index = code + base - lower
                if index == 0:
                    zeros += 1
                    if zeros >= 6:
                        return bytes(output), number, unknown
                else:
                    if index >= len(symbols):
                        raise ValueError('Symbol index out of bounds')
                    output.extend(symbols[index])
                    zeros = 0
                    if len(output) > 2_000_000:
                        raise ValueError('Decoded block exceeds probe limit')
                code = depth = 0
            else:
                depth += 1
    # A physically full block may have only a zero prefix, fewer than six null
    # symbols, or no padding at all. Blocks 214, 449 and 3578 demonstrate these
    # cases; their successors continue the text without a missing character.
    # Never follow the original C implementation's out-of-allocation read.
    if code == 0:
        return bytes(output), number, unknown
    raise ValueError('Non-padding data at physical block end')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('database', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1()
    with args.database.open('rb') as f:
        while chunk := f.read(1024 * 1024):
            digest.update(chunk)
        f.seek(0)
        header = f.read(256)
        start = struct.unpack_from('>I', header, 0)[0] + BLOCK
        end = struct.unpack_from('>I', header, 64)[0]
        if not 0 < start < end <= args.database.stat().st_size or (end-start) % BLOCK:
            raise ValueError('Invalid entry region')
        total = (end-start) // BLOCK
        invalid_headers = []
        for index in range(total):
            f.seek(start + index * BLOCK)
            number, unknown, size, count = struct.unpack('>4I', f.read(16))
            if not (16 < 16+size < BLOCK-384 and 0 < count < BLOCK):
                invalid_headers.append(index)
        samples = []
        for index in sorted({0, 1, total//4, total//2, 3*total//4, total-1}):
            f.seek(start + index * BLOCK)
            decoded, number, unknown = decode(f.read(BLOCK))
            path = args.output / f'block-{index:04d}.sgml'
            path.write_bytes(decoded)
            samples.append({'index': index, 'offset': start+index*BLOCK,
                            'block_number': number, 'unknown': unknown,
                            'decoded_bytes': len(decoded),
                            'entry_starts': len(re.findall(rb'<e(?:\s[^>]*)?>', decoded)),
                            'entry_ends': decoded.count(b'</e>'),
                            'headwords': [x.decode('ascii', 'replace') for x in re.findall(rb'<hw>(.*?)</hw>', decoded)[:8]],
                            'tags': sorted({x.decode('ascii') for x in re.findall(rb'</?([A-Za-z][A-Za-z0-9]*)', decoded)}),
                            'sha256': hashlib.sha256(decoded).hexdigest()})
    report = {'database_sha1': digest.hexdigest(), 'entry_region_start': start,
              'entry_region_end': end, 'blocks': total,
              'invalid_headers': invalid_headers, 'samples': samples,
              'limitations': ['Only six blocks decoded; full extraction unverified.',
                              'Six-zero termination follows the historical decoder heuristic.',
                              'SGML entities and pronunciation encoding are not converted.',
                              'Entry fragments may cross block boundaries.',
                              'Other database regions and original program behavior unexamined.']}
    (args.output / 'probe.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
