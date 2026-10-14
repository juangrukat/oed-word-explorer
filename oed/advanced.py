"""Offline pronunciation and grammatical indexes; no generated pronunciations."""
import argparse
from collections import Counter
from contextlib import closing
from functools import lru_cache
import json
import mmap
import re
import sqlite3
import unicodedata
import threading
from pathlib import Path
from .markup import parse, clean, normalize

POS = {'any','noun','verb','adjective','adverb','pronoun','preposition','conjunction','interjection','affix','phrase','participle','unlabelled'}
SOUND_MODES = {'rhyme','near-rhyme','sounds-like'}
VOWELS=set('iɪeɛæaɑɒɔoʊuʌəɜœøyɨɐɚɝʏɯʉɞɶɤ')
CONSONANTS=set('pbtdkgɡfvθðszʃʒhɦmnŋɲlrɹɾʀʁjwçxɣɸβɫʍʎʔ')
DIPHTHONGS={'eɪ','aɪ','ɔɪ','əʊ','aʊ','ɪə','ɛə','ʊə','oʊ','ɑɪ','ɔə','eə'}
AFFRICATES={'tʃ','dʒ','ts','dz','tɕ','dʑ'}
GROUPS=[set('pb'),set('tdθð'),set('kgɡ'),set('fvɸβ'),set('szʃʒ'),set('mnŋɲ'),set('lrɹɾʀʁɫ'),VOWELS]

@lru_cache(maxsize=4096)
def categories(value):
    checks={'noun':r'\bns?\.', 'verb':r'\bvs?\.', 'adjective':r'\ba\.|\badjs?\.',
            'adverb':r'\badv(?:b)?s?\.', 'pronoun':r'\bprons?\.', 'preposition':r'\bpreps?\.',
            'conjunction':r'\bconjs?\.', 'interjection':r'\bint(?:erj)?s?\.',
            'affix':r'\b(?:prefix|suffix|affix)\b', 'phrase':r'\bphr\.',
            'participle':r'\b(?:ppl\.|pple\.)'}
    found=tuple(k for k,p in checks.items() if re.search(p,value,re.I))
    return found or ('unlabelled',)


def analyse(value):
    """Validate one IPA form. Optional segments are expanded by forms()."""
    value=unicodedata.normalize('NFD',value.strip().strip('/[]')).replace('ɡ','g').replace('͡','').replace('͜','')
    if value.startswith('-') or value.endswith('-'):
        raise ValueError('Partial pronunciation is not a complete word form')
    if re.search(r'\b(?:see|below|above|formerly|usually|also|sometimes|originally|pronounced|pronunciation|stress|variable|now)\b',value,re.I):
        raise ValueError('Pronunciation contains a prose note')
    tokens=[];nuclei=[];stresses=[];pending=0;i=0
    while i<len(value):
        ch=value[i]
        if ch.isspace() or ch in '.-':i+=1;continue
        if ch in 'ˈˌ':
            if pending:raise ValueError('Consecutive stress marks')
            pending=1 if ch=='ˈ' else 2;i+=1;continue
        pair=value[i:i+2]
        if pair in DIPHTHONGS or pair in AFFRICATES:
            token=pair;i+=2
        elif ch in VOWELS or ch in CONSONANTS:
            token=ch;i+=1
        else:
            raise ValueError(f'Unsupported IPA symbol: {ch}')
        if i<len(value) and value[i] in 'ːˑ':token+=value[i];i+=1
        if i<len(value) and value[i] in '̩̃':token+=value[i];i+=1
        if token[0] in VOWELS or token.endswith('̩'):
            nuclei.append(len(tokens));stresses.append(pending);pending=0
        tokens.append(token)
    if pending or not nuclei or len(tokens)>48:raise ValueError('Pronunciation needs a complete vowel nucleus and at most 48 phonemes')
    if len(nuclei)==1 and not any(stresses):stresses=[1]
    primary=[i for i,s in enumerate(stresses) if s==1]
    rhyme=tokens[nuclei[primary[-1]]:] if primary else None
    return {'ipa':value,'tokens':tokens,'key':' '.join(tokens),'syllables':len(nuclei),
            'stress':''.join(map(str,stresses)) if primary else None,
            'rhyme':' '.join(rhyme) if rhyme else None,'tail':' '.join(tokens[nuclei[-1]:])}


def forms(value):
    results=[];errors=[]
    # Only explicitly written alternatives/optional segments are expanded.
    for segment in re.split(r'\s*/\s*|\s*,\s*|\s*;\s*|\s+or\s+',value):
        segment=segment.strip()
        if not segment:continue
        options=[segment]
        optional=re.findall(r'\(([^()]*)\)',segment)
        if len(optional)>3:
            errors.append(segment);continue
        for part in optional:
            options=[v for option in options for v in (option.replace('('+part+')','',1),option.replace('('+part+')',part,1))]
        for option in options:
            try:
                result=analyse(option)
                result['recorded']=segment
                result['optional']=bool(optional)
                if result['key'] not in {x['key'] for x in results}:results.append(result)
            except ValueError:
                errors.append(option)
    return results,errors


def distance(a,b,cutoff=None):
    previous=list(map(float,range(len(b)+1)))
    for i,x in enumerate(a,1):
        current=[float(i)]
        for j,y in enumerate(b,1):
            cost=0 if x==y else .55 if any(x.rstrip('ːˑ') in g and y.rstrip('ːˑ') in g for g in GROUPS) else 1.
            current.append(min(current[-1]+1,previous[j]+1,previous[j-1]+cost))
        previous=current
        if cutoff is not None and min(current)>cutoff:return cutoff+1
    return previous[-1]


def build(database,corpus,output):
    source=sqlite3.connect(database);source.row_factory=sqlite3.Row
    partial=output.with_suffix('.partial');partial.unlink(missing_ok=True)
    target=sqlite3.connect(partial)
    target.executescript('''CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);
        CREATE TABLE grammar(entry_id INTEGER,sense_id TEXT,display TEXT,category TEXT,
          PRIMARY KEY(entry_id,sense_id,category));
        CREATE INDEX grammar_category ON grammar(category,entry_id,sense_id);
        CREATE TABLE sounds(id INTEGER PRIMARY KEY,entry_id INTEGER,ipa TEXT,recorded TEXT,
          optional INTEGER,key TEXT,rhyme TEXT,tail TEXT,syllables INTEGER,stress TEXT);
        CREATE INDEX sounds_key ON sounds(key);
        CREATE INDEX sounds_rhyme ON sounds(rhyme);
        CREATE INDEX sounds_entry ON sounds(entry_id);
        CREATE INDEX sounds_tail ON sounds(tail);
        CREATE INDEX sounds_near ON sounds(coalesce(rhyme,tail));''')
    target.execute('PRAGMA synchronous=OFF');target.execute('PRAGMA journal_mode=OFF')
    issues=Counter();forms_count=0;entries_count=0
    for row in source.execute('SELECT id,pos,pronunciation FROM entries'):
        for category in categories(row['pos']):
            target.execute('INSERT INTO grammar VALUES(?,?,?,?)',(row['id'],'',row['pos'],category))
        parsed,errors=forms(row['pronunciation'])
        if parsed:entries_count+=1
        for error in errors:issues[error]+=1
        for item in parsed:
            target.execute('INSERT INTO sounds(entry_id,ipa,recorded,optional,key,rhyme,tail,syllables,stress) VALUES(?,?,?,?,?,?,?,?,?)',
                           (row['id'],item['ipa'],item['recorded'],int(item['optional']),item['key'],item['rhyme'],item['tail'],item['syllables'],item['stress']))
            forms_count+=1
    print(f'Indexed {forms_count:,} pronunciations from {entries_count:,} entries',flush=True)
    with open(corpus,'rb') as f,mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as data:
        for row in source.execute("SELECT id,entry_id,source_offset FROM senses WHERE tag='sub'"):
            start=row['source_offset'];end=data.find(b'</sub>',start)
            if end<0:raise ValueError('Subentry source boundary missing')
            tree,_=parse(data[start:end+6].decode('ascii'))
            sub=next(tree.walk('sub'));pos=[]
            # Only direct subentry grammar, excluding cited words/quotations.
            for child in sub.children:
                if not isinstance(child,str) and child.tag=='ps':pos.append(clean(child,exclude={'hm'}))
            display=' '.join(dict.fromkeys(pos))
            for category in categories(display):target.execute('INSERT INTO grammar VALUES(?,?,?,?)',(row['entry_id'],row['id'],display,category))
    report={'valid_pronunciation_entries':entries_count,'pronunciation_forms':forms_count,
            'strict_rhyme_forms':target.execute('SELECT count(*) FROM sounds WHERE rhyme IS NOT NULL').fetchone()[0],
            'unsupported_forms':sum(issues.values()),'unsupported_examples':dict(issues.most_common(20)),
            'grammar_rows':target.execute('SELECT count(*) FROM grammar').fetchone()[0],
            'corpus_sha256':json.loads(source.execute("SELECT value FROM metadata WHERE key='corpus_sha256'").fetchone()[0])}
    for key,value in report.items():target.execute('INSERT INTO metadata VALUES(?,?)',(key,json.dumps(value)))
    target.commit()
    assert target.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    target.close();source.close();partial.replace(output)
    output.with_suffix('.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)


class Advanced:
    def __init__(self,path):
        self.path=Path(path)
        self._lock=threading.RLock()
        with closing(sqlite3.connect(self.path)) as c:
            self.profiles={r[0]:tuple(r[0].split()) for r in c.execute('SELECT DISTINCT key FROM sounds')}
            self.tails={r[0]:tuple(r[0].split()) for r in c.execute('SELECT DISTINCT coalesce(rhyme,tail) FROM sounds')}

    def nearest(self,key,mode):
        with self._lock:
            return self._nearest(key,mode)

    @lru_cache(maxsize=128)
    def _nearest(self,key,mode):
        tokens=tuple(key.split());profiles=self.tails if mode=='near-rhyme' else self.profiles
        candidates=[]
        for other,phones in profiles.items():
            if abs(len(phones)-len(tokens))>2:continue
            score=distance(tokens,phones,2.05)
            if score<=2.05:candidates.append((score,other))
        return tuple(sorted(candidates)[:800])


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--database',type=Path,default=Path('data/oed.sqlite'))
    parser.add_argument('--corpus',type=Path,default=Path('data/corpus.sgml'))
    parser.add_argument('--output',type=Path,default=Path('data/advanced.sqlite'))
    args=parser.parse_args();build(args.database,args.corpus,args.output)

if __name__=='__main__':main()
