"""Actual mixed API load plus corpus-backed phonetic acceptance checks."""
import concurrent.futures
import json
import statistics
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1]
BASE='http://127.0.0.1:8765/api/search?'
CASES=[{'q':'light','mode':'rhyme','pos':'noun'},
       {'q':'nation','mode':'rhyme','syllables':'2','stress':'10'},
       {'q':'cat','mode':'near-rhyme'}, {'q':'light','mode':'sounds-like'},
       {'q':'lament*','pos':'verb'}, {'q':'poem mourning','mode':'definitions','pos':'noun'},
       {'q':'read','mode':'rhyme'}]

def request(case):
    began=time.perf_counter()
    with urlopen(BASE+urlencode(case),timeout=30) as response:
        assert response.status==200
        data=json.load(response)
    assert len(data['results'])<=40
    if case['q']=='read':assert data['needs_pronunciation']
    return {'case':case,'seconds':round(time.perf_counter()-began,3),'results':len(data['results'])}

with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
    results=list(executor.map(request,CASES*8))
times=[r['seconds'] for r in results]
report={'requests':len(results),'concurrency':8,'errors':0,
        'median_seconds':round(statistics.median(times),3),
        'p95_seconds':sorted(times)[int(.95*(len(times)-1))],
        'max_seconds':max(times),'examples':results[:7]}
def require_word(case,expected):
    offset=0
    while True:
        with urlopen(BASE+urlencode({**case,'offset':offset}),timeout=30) as response:data=json.load(response)
        if any(x['headword']==expected for x in data['results']):return
        offset=data.get('next_offset')
        assert offset is not None,(case,expected)

require_word(CASES[0],'night')
require_word(CASES[1],'station')
# Pronunciation choice is carried by the API rather than inferred from spelling.
with urlopen(BASE+urlencode({'q':'read','mode':'rhyme'})) as response:choices=json.load(response)['pronunciations']
for ipa,expected in [('riːd','reed'),('rɛd','red')]:
    choice=next(x for x in choices if x['ipa']==ipa)
    require_word({'q':'read','mode':'rhyme','pronunciation':choice['key']},expected)
report['read_variant_checks']='Both /riːd/→reed and /rɛd/→red pass.'
(ROOT/'docs/advanced-stress.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(report,ensure_ascii=False,indent=2))
