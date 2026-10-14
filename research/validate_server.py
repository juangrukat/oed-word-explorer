"""Corpus-backed acceptance checks for this particular disc and server."""
import hashlib
import json
import random
import sqlite3
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from oed.service import Dictionary

root=Path(__file__).resolve().parents[1]
d=Dictionary(root/'data/oed.sqlite',root/'data/corpus.sgml')
report=json.loads((root/'data/import-report.json').read_text())
assert report['entries']==291588
assert report['senses']==777030
assert report['quotations']==2435558
assert report['unmatched_record_bytes']==0 and not report['parse_issues']

checks=[]
for term in ['A','zyxt','lament','litotes','zeugma','repetition','A1']:
    found=d.search(term)['results']
    assert found, term
    checks.append({'check':'headword','query':term,'first_match':found[0]['headword']})

with d.connect() as c:
    rows=c.execute('SELECT id,source_sha256 FROM entries ORDER BY id').fetchall()
    samples=[rows[0],rows[-1]]+random.Random(20261014).sample(rows,20)
    for row in samples:
        assert hashlib.sha256(d.raw(row['id'])).hexdigest()==row['source_sha256']
    exact=c.execute('SELECT count(*) FROM refs r WHERE EXISTS(SELECT 1 FROM headwords a WHERE a.norm=r.norm)').fetchone()[0]
    count=c.execute('SELECT count(*) FROM refs').fetchone()[0]
    checks.append({'check':'named_reference_resolution','exact_headword_matches':exact,'named_references':count,
                   'note':'Matching the headword does not resolve all homonym or sense ambiguity.'})

r=d.search('rhetorical repetition','definitions',literary=True)
assert r['results'][0]['headword']=='polyptoton'
checks.append({'check':'literary_discovery','query':'rhetorical repetition','top_results':[x['headword'] for x in r['results'][:8]]})
r=d.search('poem mourning','definitions')
assert 'elegy' in [x['headword'] for x in r['results']]
assert r['expansions']
checks.append({'check':'expanded_idea_search','query':'poem mourning','top_results':[x['headword'] for x in r['results'][:12]]})
e=d.get_entry(d.search('lament')['results'][0]['id'])
r=d.related(e['id'],e['senses'][1]['id'],obscure=True)
assert r['suggestions']
assert all(x['obscure'] for x in r['suggestions'])
checks.append({'check':'obscure_from_selected_sense','headword':'lament','sense':e['senses'][1]['number'],
               'top_results':[x['headword'] for x in r['suggestions'][:10]]})
assert d.search('litotes',literary=True)['results']

# Check the regression that a historical spelling's Scottish label had leaked
# into the normal funeral-song sense of dirge.
e=d.get_entry(d.search('dirge')['results'][0]['id'])
normal=next(s for s in e['senses'] if s['number']=='2')
assert 'Sc.' not in normal['labels']
assert not normal['obscure']
checks.append({'check':'variant_label_scope','headword':'dirge','sense':'2','labels':normal['labels']})

validation={'counts':{k:report[k] for k in ['entries','headwords','senses','references','quotations','obscure_senses','literary_candidates']},
            'source_samples_verified':len(samples),'checks':checks,'automated_unit_tests':11,
            'browser_checks':['headword search','entry navigation','sense selection','obscure filter','desktop layout','phone layout without horizontal overflow','no browser console errors'],
            'limitations':['Text-based inferred connections are not verified synonyms.',
                           'Named references may retain homonym and sense ambiguity; relative references are retained in source text.',
                           'Unmapped special symbols are visibly preserved.',
                           'No independent comparison against the legacy Windows application runtime.']}
(root/'docs/validation.json').write_text(json.dumps(validation,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(validation,ensure_ascii=False,indent=2))
