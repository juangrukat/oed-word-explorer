"""Recover the corpus from the checksum-matched OED2 database."""
import argparse
import collections
import hashlib
import json
import re
import struct
from pathlib import Path
from probe_database import BLOCK, decode

p = argparse.ArgumentParser()
p.add_argument('database', type=Path)
p.add_argument('--output', type=Path, default=Path('data'))
a = p.parse_args()
a.output.mkdir(parents=True, exist_ok=True)
sha = hashlib.sha1()
with a.database.open('rb') as source:
    while chunk := source.read(1024 * 1024):
        sha.update(chunk)
    if sha.hexdigest() != '626fab18cc9a25feafcf4080901c834e3ca05af7':
        raise ValueError('Unrecognized database: this decoder is verified for the supplied disc only')
    source.seek(0)
    header = source.read(256)
    start = struct.unpack_from('>I', header, 0)[0] + BLOCK
    end = struct.unpack_from('>I', header, 64)[0]
    if not 0 < start < end <= a.database.stat().st_size or (end-start) % BLOCK:
        raise ValueError('Invalid entry region')
    count = (end-start)//BLOCK
    offsets = []
    tags = collections.Counter()
    entities = collections.Counter()
    digest = hashlib.sha256()
    size = 0
    with (a.output/'corpus.sgml.partial').open('wb') as out:
        source.seek(start)
        for i in range(count):
            try:
                decoded, number, unknown = decode(source.read(BLOCK))
            except ValueError as error:
                raise ValueError(f'Block {i}: {error}') from error
            if offsets and number != offsets[-1]['header_number'] + offsets[-1]['header_unknown']:
                raise ValueError(f'Non-contiguous logical block positions at {i}')
            offsets.append({'block': i, 'database_offset': start+i*BLOCK,
                            'corpus_offset': size, 'decoded_bytes': len(decoded),
                            'header_number': number, 'header_unknown': unknown})
            out.write(decoded)
            digest.update(decoded)
            size += len(decoded)
            tags.update(x.decode('ascii') for x in re.findall(rb'</?([A-Za-z][A-Za-z0-9]*)', decoded))
            entities.update(x.decode('ascii') for x in re.findall(rb'&([A-Za-z][A-Za-z0-9]*)\.', decoded))
            if i % 500 == 0:
                print(f'Decoded {i+1}/{count} blocks ({size:,} bytes)', flush=True)
    (a.output/'corpus.sgml.partial').replace(a.output/'corpus.sgml')
    manifest = {'database_sha1': sha.hexdigest(), 'region_start': start, 'region_end': end,
                'blocks_decoded': count, 'decoded_bytes': size, 'corpus_sha256': digest.hexdigest(),
                'blocks': offsets, 'tags': dict(tags.most_common()), 'entities': dict(entities.most_common()),
                'termination': 'All blocks ended at six null symbols or physical end with null/zero padding; all reads bounds checked.'}
    (a.output/'extraction.json').write_text(json.dumps(manifest, indent=2)+'\n')
print(f'Complete: {count} blocks, {size:,} bytes; SHA-256 {digest.hexdigest()}', flush=True)
