"""Validate record boundaries and import the recovered corpus atomically."""
import argparse
import collections
import hashlib
import json
import mmap
import re
import sqlite3
import time
from pathlib import Path
from .markup import entry_data, clean, ENTITY, ENTITIES, OBSCURE, LITERARY, normalize

ENTRY = re.compile(rb'<(?P<tag>e|ve)(?=[ >])[^>]*>.*?</(?P=tag)>', re.S)
SCHEMA = '''
CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE entries(id INTEGER PRIMARY KEY, headword TEXT NOT NULL, norm TEXT NOT NULL,
 kind TEXT NOT NULL, pos TEXT NOT NULL, homonym TEXT NOT NULL, pronunciation TEXT NOT NULL,
 labels TEXT NOT NULL, source_length INTEGER NOT NULL, source_sha256 TEXT NOT NULL);
CREATE INDEX entries_norm ON entries(norm);
CREATE TABLE headwords(entry_id INTEGER NOT NULL REFERENCES entries(id), headword TEXT NOT NULL, norm TEXT NOT NULL, sense_id TEXT);
CREATE INDEX headwords_norm ON headwords(norm);
CREATE INDEX headwords_entry ON headwords(entry_id);
CREATE TABLE senses(id TEXT PRIMARY KEY, entry_id INTEGER NOT NULL REFERENCES entries(id),
 parent_id TEXT, tag TEXT NOT NULL, number TEXT NOT NULL, definition TEXT NOT NULL,
 headword TEXT NOT NULL, labels TEXT NOT NULL, obscure INTEGER NOT NULL,
 literary INTEGER NOT NULL, source_offset INTEGER NOT NULL);
CREATE INDEX senses_entry ON senses(entry_id);
CREATE INDEX senses_obscure ON senses(obscure);
CREATE INDEX senses_literary ON senses(literary);
CREATE TABLE refs(id INTEGER PRIMARY KEY, entry_id INTEGER NOT NULL REFERENCES entries(id),
 sense_id TEXT, target TEXT NOT NULL, norm TEXT NOT NULL, text TEXT NOT NULL,
 context TEXT NOT NULL, pos TEXT NOT NULL, homonym TEXT NOT NULL, target_sense TEXT NOT NULL);
CREATE INDEX refs_source ON refs(entry_id);
CREATE INDEX refs_target ON refs(norm);
CREATE TABLE quotations(entry_id INTEGER NOT NULL REFERENCES entries(id), text TEXT NOT NULL);
CREATE VIRTUAL TABLE definitions USING fts5(definition, headword, labels,
 content='senses', content_rowid='rowid', tokenize='porter unicode61 remove_diacritics 2');
CREATE VIRTUAL TABLE terms USING fts5vocab(definitions, 'row');
CREATE VIRTUAL TABLE quotation_search USING fts5(text, content='quotations', content_rowid='rowid',
 tokenize='porter unicode61 remove_diacritics 2');
'''


def build(corpus, database):
    began = time.monotonic()
    manifest = json.loads(corpus.with_name('extraction.json').read_text())
    partial = database.with_suffix('.partial')
    partial.unlink(missing_ok=True)
    conn = sqlite3.connect(partial)
    conn.executescript(SCHEMA)
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA synchronous=OFF')
    conn.execute('PRAGMA journal_mode=OFF')
    issues = collections.Counter()
    issue_examples = []
    unresolved = collections.Counter()
    seen = collections.Counter()
    opening_counts = closing_counts = None
    previous = 0
    gap_bytes = 0
    gaps = []
    with corpus.open('rb') as source, mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ) as data:
        digest = hashlib.sha256(data).hexdigest()
        if digest != manifest['corpus_sha256']:
            raise ValueError('Corpus digest differs from extraction manifest')
        opening_counts = {tag: len(re.findall(rb'<'+tag.encode()+rb'(?=[ >])', data)) for tag in ['e','ve']}
        closing_counts = {tag: data.count(b'</'+tag.encode()+b'>') if hasattr(data,'count') else len(re.findall(rb'</'+tag.encode()+rb'>', data)) for tag in ['e','ve']}
        for index, match in enumerate(ENTRY.finditer(data)):
            offset = match.start()
            gap = data[previous:offset].strip()
            if gap:
                gap_bytes += len(gap)
                if len(gaps)<10:
                    gaps.append({'offset':previous, 'bytes':len(gap), 'preview':repr(gap[:100])})
            previous = match.end()
            raw = match.group().decode('ascii')
            d = entry_data(raw, offset)
            seen[d['kind']] += 1
            for issue in d['issues']:
                issues[issue.split(' at ')[0]] += 1
                if len(issue_examples)<20:
                    issue_examples.append({'entry':offset,'headword':d['headword'],'issue':issue})
            unresolved.update(m for m in ENTITY.findall(raw) if m not in ENTITIES)
            conn.execute('INSERT INTO entries VALUES(?,?,?,?,?,?,?,?,?,?)',
                         (offset,d['headword'],d['norm'],d['kind'],d['pos'],d['homonym'],
                          d['pronunciation'],json.dumps(d['labels']),len(match.group()),
                          hashlib.sha256(match.group()).hexdigest()))
            for hw in d['headwords']:
                conn.execute('INSERT INTO headwords VALUES(?,?,?,NULL)',(offset,hw,normalize(hw)))
            for sense in d['senses']:
                sense_headword = sense.get('headword', d['headword'])
                if sense['tag']=='sub' and sense_headword != d['headword']:
                    conn.execute('INSERT INTO headwords VALUES(?,?,?,?)',(offset,sense_headword,normalize(sense_headword),sense['id']))
                labels = ' | '.join(sense['labels'])
                # Explicit inherited status/usage labels, plus concise leading
                # definition labels. Historical quotations are never inspected.
                leading = sense['definition'][:100]
                obscure = bool(OBSCURE.search(labels) or re.match(r'^(?:Obs\.|Obsolete\b|Rare\b|Archaic\b|dial\.)', leading, re.I))
                literary = bool(LITERARY.search(labels + ' ' + sense['definition']))
                conn.execute('INSERT INTO senses VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                             (sense['id'],offset,sense['parent_id'],sense['tag'],sense['number'],
                              sense['definition'],sense_headword,json.dumps(sense['labels']),
                              int(obscure),int(literary),offset+sense['offset']))
            for ref in d['references']:
                conn.execute('INSERT INTO refs(entry_id,sense_id,target,norm,text,context,pos,homonym,target_sense) VALUES(?,?,?,?,?,?,?,?,?)',
                             (offset,ref['sense_id'],ref['target'],normalize(ref['target']),ref['text'],
                              ref['context'],ref['pos'],ref['homonym'],ref['target_sense']))
            for q in d['tree'].walk('q'):
                conn.execute('INSERT INTO quotations VALUES(?,?)', (offset, clean(q)))
            if index % 10000 == 0:
                conn.commit()
                print(f'Imported {index+1:,} entries ({d["headword"]})', flush=True)
        tail = data[previous:].strip()
        if tail:
            gap_bytes += len(tail)
            gaps.append({'offset':previous,'bytes':len(tail),'preview':repr(tail[:100])})
    if any(seen[tag]!=opening_counts[tag] for tag in opening_counts) or opening_counts != closing_counts:
        raise ValueError(f'Entry boundary mismatch: imported={dict(seen)}, starts={opening_counts}, ends={closing_counts}')
    if gap_bytes:
        raise ValueError(f'Unparsed corpus outside entries: {gaps}')
    conn.execute("INSERT INTO definitions(definitions) VALUES('rebuild')")
    conn.execute("INSERT INTO quotation_search(quotation_search) VALUES('rebuild')")
    conn.execute("INSERT INTO definitions(definitions,rank) VALUES('integrity-check',1)")
    conn.execute("INSERT INTO quotation_search(quotation_search,rank) VALUES('integrity-check',1)")
    report = {'entries': sum(seen.values()), 'main_entries': seen['e'], 'variant_entries':seen['ve'],
              'headwords':conn.execute('SELECT count(*) FROM headwords').fetchone()[0],
              'senses':conn.execute('SELECT count(*) FROM senses').fetchone()[0],
              'references':conn.execute('SELECT count(*) FROM refs').fetchone()[0],
              'quotations':conn.execute('SELECT count(*) FROM quotations').fetchone()[0],
              'obscure_senses':conn.execute('SELECT count(*) FROM senses WHERE obscure=1').fetchone()[0],
              'literary_candidates':conn.execute('SELECT count(*) FROM senses WHERE literary=1').fetchone()[0],
              'unmatched_record_bytes':gap_bytes, 'parse_issues':dict(issues), 'issue_examples':issue_examples,
              'unmapped_entities':dict(unresolved.most_common()), 'corpus_sha256':digest,
              'database_sha1':manifest['database_sha1'], 'elapsed_seconds':round(time.monotonic()-began,1)}
    for key,value in report.items():
        conn.execute('INSERT INTO metadata VALUES(?,?)',(key,json.dumps(value)))
    conn.commit()
    integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
    if integrity != 'ok':
        raise ValueError(integrity)
    if conn.execute('PRAGMA foreign_key_check').fetchall():
        raise ValueError('Foreign key check failed')
    conn.close()
    partial.replace(database)
    (database.parent/'import-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in {'unmapped_entities','issue_examples'}},indent=2),flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--corpus',type=Path,default=Path('data/corpus.sgml'))
    parser.add_argument('--database',type=Path,default=Path('data/oed.sqlite'))
    args=parser.parse_args()
    build(args.corpus,args.database)

if __name__ == '__main__':
    main()
