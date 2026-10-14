"""Check wildcard correctness against an independent regex oracle and load-test HTTP."""
import concurrent.futures
import json
import random
import re
import sqlite3
import statistics
import time
import unicodedata
from pathlib import Path
import sys
from urllib.parse import urlencode
from urllib.request import urlopen
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from oed.service import Dictionary
from oed.markup import normalize

root=Path(__file__).resolve().parents[1]
d=Dictionary(root/'data/oed.sqlite',root/'data/corpus.sgml')
patterns=['la?ent*','lam?nt*','lament*','?ament','*lament*','?','*','**','???','*ing',
          'A?','a??','*?*','*tion','%','_','\\','la$ent*',"' OR 1=1 --",'[abc]*',
          'ÉLÉG*','LAMENT*','nonexistentzzzz*','*'*300,'?'*300,'*?*?*?*?*?*?*?']
with d.connect() as c:
    rows=[dict(r) for r in c.execute('SELECT entry_id,headword,norm,sense_id FROM headwords')]
rng=random.Random(20261014)
for row in rng.sample([r for r in rows if 4<=len(r['norm'])<=18 and r['norm'].isascii()],45):
    chars=list(row['norm']);chars[rng.randrange(len(chars))]='?'
    patterns.append(''.join(chars[:rng.randrange(2,len(chars)+1)])+'*')
checks=[]
for pattern in patterns:
    # Independently preserve wildcard characters, unlike source headword
    # normalization, which strips editorial asterisks.
    norm=unicodedata.normalize('NFKD',pattern.casefold())
    norm=''.join(ch for ch in norm if not unicodedata.combining(ch) and ch not in 'ˈˌ†‡' and not ch.isspace())
    oracle=''.join('.*' if ch=='*' else '.' if ch=='?' else re.escape(ch) for ch in norm)
    if '*' not in norm and '?' not in norm:
        oracle+='.*'
    regex=re.compile(oracle+'\\Z',re.S)
    matches={(r['entry_id'],r['sense_id']) for r in rows if regex.fullmatch(r['norm'])}
    began=time.perf_counter();result=d.search(pattern);elapsed=time.perf_counter()-began
    returned={(r['id'],r['matched_sense_id']) for r in result['results']}
    assert returned<=matches,(pattern,'unexpected match')
    assert len(returned)==min(40,len(matches)),(pattern,len(returned),len(matches))
    checks.append({'pattern':pattern,'matching_entries_or_subentries':len(matches),'returned':len(returned),'seconds':round(elapsed,4)})

# Actual concurrent HTTP requests, not just calls to a query function.
load_patterns=['la?ent*','lament*','*ing','?','*','*tion','nonexistentzzzz*','%']*12
rng.shuffle(load_patterns)
def request(pattern):
    began=time.perf_counter()
    with urlopen('http://127.0.0.1:8765/api/search?'+urlencode({'q':pattern}),timeout=30) as response:
        assert response.status==200
        result=json.load(response)
    assert len(result['results'])<=40
    return time.perf_counter()-began
began=time.perf_counter()
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
    durations=list(executor.map(request,load_patterns))
report={'correctness_patterns':len(checks),'oracle_headword_rows':len(rows),'correctness':checks,
        'concurrent_http':{'requests':len(durations),'workers':8,'errors':0,'elapsed_seconds':round(time.perf_counter()-began,3),
                           'median_seconds':round(statistics.median(durations),3),
                           'p95_seconds':round(sorted(durations)[int(.95*(len(durations)-1))],3),
                           'max_seconds':round(max(durations),3)},
        'phonetic_search':'Phonetic and grammar load checks are recorded separately in docs/advanced-stress.json.'}
(root/'docs/search-stress.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k!='correctness'},indent=2))
