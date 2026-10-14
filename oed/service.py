"""Read-only dictionary queries and explainable connections."""
from collections import Counter
from contextlib import contextmanager
import math
import json
import re
import sqlite3
import threading
from pathlib import Path
from .markup import entry_data, clean, normalize, words
from .advanced import Advanced, POS, SOUND_MODES
from .sound_search import sound_search

STOP = set('''the and for that with this from are was were been being have has had not but which
who whom whose into its their his her our your you they them these those such some any
all one two three used use also hence esp especially properly generally usually often
said called name form kind sort thing things person persons pertaining relating having
relating denoting expressing regarded particular sense sometimes formerly now see cf
etc obs obsolete rare dial archaic adj adv noun verb subst trans intr part participle
plural singular chiefly applied certain similar very more most less other same thus
than when where what how may can could would should shall will does did above below
first second last latter former following preceding before after according belonging
one another like resembling something someone without through under over upon among
about between each both either neither though there here only otherwise originally
place manner way state quality action act make made become consisting anything much
many several various often chiefly general specifically special reference instance
term word words definition example examples expression express usage quotes quotation
'''.split())

class Dictionary:
    def __init__(self, database, corpus):
        self.database = Path(database).resolve()
        self.corpus = Path(corpus).resolve()
        self.advanced_path = self.database.with_name('advanced.sqlite')
        self._sound_index = None
        self._sound_lock = threading.Lock()
        self._sound_stamp = None
        self._verified_index_stamp = None

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.database.as_uri() + '?mode=ro', uri=True)
        conn.row_factory = sqlite3.Row
        if self.advanced_path.exists():
            conn.execute('ATTACH DATABASE ? AS advanced',(self.advanced_path.as_uri()+'?mode=ro',))
            stamp=(self.database.stat().st_mtime_ns,self.advanced_path.stat().st_mtime_ns)
            if self._verified_index_stamp!=stamp:
                main=conn.execute("SELECT value FROM metadata WHERE key='corpus_sha256'").fetchone()[0]
                auxiliary=conn.execute("SELECT value FROM advanced.metadata WHERE key='corpus_sha256'").fetchone()[0]
                if main!=auxiliary:
                    conn.close()
                    raise ValueError('Advanced index belongs to another corpus; rebuild it with python3 -m oed.advanced')
                self._verified_index_stamp=stamp
        try:
            yield conn
        finally:
            conn.close()

    @property
    def sound_index(self):
        stamp=self.advanced_path.stat().st_mtime_ns
        if self._sound_index is None or self._sound_stamp!=stamp:
            with self._sound_lock:
                if self._sound_index is None or self._sound_stamp!=stamp:
                    self._sound_index=Advanced(self.advanced_path)
                    self._sound_stamp=stamp
        return self._sound_index

    def pos_clause(self, entry, sense, pos):
        if pos=='any':return ''
        if not self.advanced_path.exists():raise ValueError('Grammar index is missing; run python3 -m oed.advanced')
        return f" AND EXISTS(SELECT 1 FROM advanced.grammar g WHERE g.entry_id={entry} AND g.sense_id=coalesce({sense},'') AND g.category=?) "

    def display_pos(self, connection, entry, sense, fallback):
        if not sense or not self.advanced_path.exists():return fallback
        row=connection.execute('SELECT display FROM advanced.grammar WHERE entry_id=? AND sense_id=? LIMIT 1',(entry,sense)).fetchone()
        return row['display'] if row else ''

    def status(self):
        with self.connect() as c:
            result={r['key']:json.loads(r['value']) for r in c.execute('SELECT key,value FROM metadata')
                    if r['key'] not in {'issue_examples','unmapped_entities','parse_issues'}}
            if self.advanced_path.exists():
                result['phonetic_entries']=json.loads(c.execute("SELECT value FROM advanced.metadata WHERE key='valid_pronunciation_entries'").fetchone()[0])
            return result

    @staticmethod
    def pack(row):
        d = dict(row)
        if 'labels' in d:
            d['labels'] = json.loads(d['labels'])
        return d

    @staticmethod
    def query(value):
        tokens = list(dict.fromkeys(w for w in words(value) if w not in STOP))[:16]
        return ' OR '.join('"'+w+'"' for w in tokens), tokens

    def discovery_query(self, connection, tokens):
        """Expand multiword ideas using cited headword definitions, not a
        hidden synonym list. Each group is inferred and returned to the UI.
        """
        groups=[]
        expansions=[]
        generic={'work','piece','composition','facts','thoughts','feelings','addition',
                 'critics','order','theme','treatment','qualities','mod','quot','quots',
                 'held','deserve','poet','poetical','expressed','eloquently'}
        for token in tokens[:6]:
            additions=[]
            row=connection.execute('''SELECT s.definition,e.id,e.headword FROM headwords a
                JOIN entries e ON e.id=a.entry_id JOIN senses s ON s.entry_id=e.id
                WHERE a.norm=? AND e.kind='e' AND s.tag!='sub'
                ORDER BY e.id,s.rowid LIMIT 1''',(normalize(token),)).fetchone()
            if row:
                lead=re.sub(r'\([^)]*\)','',row['definition'][:240])
                additions=list(dict.fromkeys(w for w in words(lead) if w!=token and w not in STOP
                                             and w not in generic and len(w)>3))[:7]
            group=list(dict.fromkeys([token]+additions))
            groups.append('definition:('+' OR '.join('"'+w+'"' for w in group)+')')
            if additions:
                expansions.append({'term':token,'additions':additions,'entry_id':row['id'],
                                   'headword':row['headword'],'definition':row['definition']})
        return groups,expansions

    def search(self, query, mode='headword', obscure=False, literary=False, limit=40,
               pos='any', syllables=None, stress='', pronunciation='', input_type='word'):
        if pos not in POS:raise ValueError('Unknown part of speech')
        if syllables is not None and not 1<=syllables<=16:raise ValueError('Syllables must be between 1 and 16')
        if stress and not re.fullmatch(r'[012?]{1,16}',stress):raise ValueError('Stress uses 0, 1, 2 or ?, up to 16 syllables')
        if mode not in {'headword','definitions','quotations'} | SOUND_MODES:raise ValueError('Unknown search mode')
        if mode not in SOUND_MODES and (syllables is not None or stress):raise ValueError('Syllable and stress filters require sound search')
        query = query.strip()[:300]
        if not query:
            return {'results':[], 'query':query}
        if mode in SOUND_MODES:
            return sound_search(self,query,mode,pos,obscure,literary,syllables,stress,pronunciation,input_type,limit)
        with self.connect() as c:
            if mode == 'headword':
                norm = normalize(query, pattern=True)
                if '*' in norm or '?' in norm:
                    # Translate shell wildcards, escaping SQL wildcard literals.
                    pattern = norm.replace('\\','\\\\').replace('%','\\%').replace('_','\\_').replace('*','%').replace('?','_')
                else:
                    pattern = norm.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
                rows = c.execute('''SELECT e.*,a.headword AS matched_headword,a.sense_id AS matched_sense_id
                    FROM headwords a JOIN entries e ON e.id=a.entry_id WHERE a.norm LIKE ? ESCAPE '\\'
                    AND (?=0 OR EXISTS(SELECT 1 FROM senses s WHERE s.entry_id=e.id AND s.obscure=1))
                    AND (?=0 OR EXISTS(SELECT 1 FROM senses s WHERE s.entry_id=e.id AND s.literary=1))
                    '''+self.pos_clause('e.id','a.sense_id',pos)+''' ORDER BY a.norm!=?,length(a.norm),a.norm,e.id LIMIT ?''',
                    (pattern,int(obscure),int(literary),*((pos,) if pos!='any' else ()),norm,limit*3)).fetchall()
                results = []
                seen=set()
                for row in rows:
                    key=(row['id'],row['matched_sense_id'])
                    if key in seen:
                        continue
                    seen.add(key)
                    d=self.pack(row)
                    s=c.execute('SELECT definition,labels FROM senses WHERE entry_id=? AND (? IS NULL OR id=?) ORDER BY rowid LIMIT 1',
                                (row['id'],row['matched_sense_id'],row['matched_sense_id'])).fetchone()
                    d['headword']=row['matched_headword']
                    d['pos']=self.display_pos(c,row['id'],row['matched_sense_id'],row['pos'])
                    d.update({'definition':s['definition'] if s else '', 'connection':'Headword match'})
                    results.append(d)
                    if len(results)>=limit:
                        break
            else:
                match,tokens=self.query(query)
                expansions=[]
                if not match:
                    return {'query':query,'results':[], 'notice':'Try a specific content word such as mourning, stanza, or silence.'}
                if mode == 'quotations':
                    rows = c.execute('''SELECT q.entry_id,e.headword,e.pos,e.homonym,e.labels,
                        q.text AS definition,bm25(quotation_search) AS score
                        FROM quotation_search JOIN quotations q ON q.rowid=quotation_search.rowid
                        JOIN entries e ON e.id=q.entry_id
                        WHERE quotation_search MATCH ?
                        AND (?=0 OR EXISTS(SELECT 1 FROM senses s WHERE s.entry_id=e.id AND s.obscure=1))
                        AND (?=0 OR EXISTS(SELECT 1 FROM senses s WHERE s.entry_id=e.id AND s.literary=1))
                        '''+self.pos_clause('e.id',"''",pos)+''' ORDER BY score LIMIT ?''',(match,int(obscure),int(literary),*((pos,) if pos!='any' else ()),limit*3)).fetchall()
                else:
                    original_match='definition:('+match+')'
                    groups=[]
                    constraints=''
                    group_args=[]
                    if len(tokens)>1:
                        strict=' AND '.join('definition:"'+w+'"' for w in tokens)
                        strict_count=c.execute('SELECT count(*) FROM (SELECT rowid FROM definitions WHERE definitions MATCH ? LIMIT 3)',(strict,)).fetchone()[0]
                        if strict_count>=3:
                            match=strict
                        else:
                            groups,expansions=self.discovery_query(c,tokens)
                            match=' OR '.join(groups)
                            constraints=''.join(' AND s.entry_id IN (SELECT sg.entry_id FROM definitions JOIN senses sg ON sg.rowid=definitions.rowid WHERE definitions MATCH ?)' for _ in groups)
                            group_args=groups
                    else:
                        match=original_match
                    rows = c.execute('''SELECT s.*,e.pos,e.homonym,bm25(definitions,1.0,0.0,0.0) AS score
                        FROM definitions JOIN senses s ON s.rowid=definitions.rowid
                        JOIN entries e ON e.id=s.entry_id
                        WHERE definitions MATCH ? AND (?=0 OR s.obscure=1) AND (?=0 OR s.literary=1)
                        '''+constraints+self.pos_clause('e.id',"CASE WHEN s.tag='sub' THEN s.id ELSE '' END",pos)+' ORDER BY score LIMIT ?',
                        (match,int(obscure),int(literary),*group_args,*((pos,) if pos!='any' else ()),limit*5)).fetchall()
                results=[]
                seen=set()
                for row in rows:
                    d=self.pack(row)
                    if mode=='definitions' and d['tag']=='sub':
                        d['pos']=self.display_pos(c,d['entry_id'],d['id'],d['pos'])
                    # Keep multiple distinct senses, but do not fill the result
                    # list with quotations from one entry.
                    key=d['entry_id'] if mode=='quotations' or (mode=='definitions' and groups) else d['id']
                    if key in seen:
                        continue
                    seen.add(key)
                    d['connection']='Quotation text match' if mode=='quotations' else 'Definition text match; relevance is inferred'
                    d['matched_terms']=[w for w in tokens if w in d['definition'].lower()]
                    if mode=='definitions' and groups:
                        support=[]
                        for group in groups:
                            supporting=c.execute('''SELECT s.id,s.definition FROM definitions JOIN senses s ON s.rowid=definitions.rowid
                                WHERE definitions MATCH ? AND s.entry_id=? ORDER BY length(s.definition) LIMIT 1''',(group,d['entry_id'])).fetchone()
                            if supporting and supporting['id']!=d['id'] and supporting['id'] not in {x['id'] for x in support}:
                                support.append(dict(supporting))
                        d['supporting_senses']=support
                    if mode=='definitions':
                        sense_count=c.execute('SELECT count(*) FROM senses WHERE entry_id=?',(d['entry_id'],)).fetchone()[0]
                        # Broad, many-sense words should not dominate specialist
                        # terms merely because they offer more matching text.
                        d['discovery_score']=d['score']/math.sqrt(1+sense_count)
                        if literary and any(re.search(r'\b(?:Rhet|Pros|Poet)\.',label,re.I) for label in d['labels']):
                            d['discovery_score']*=1.6
                    results.append(d)
                    if len(results)>=limit*3:
                        break
                if mode=='definitions':
                    results.sort(key=lambda d:d['discovery_score'])
                results=results[:limit]
            notice='Literary candidates are identified from definition text and usage labels; inspect the sense for evidence.' if literary else ''
            if mode=='definitions' and expansions:
                notice='Ideas broadened using dictionary definitions: '+ '; '.join(x['term']+' → '+', '.join(x['additions']) for x in expansions)+'. Concepts may match different senses; supporting definitions are shown.'
            return {'query':query,'mode':mode,'results':results,
                    'expansions':expansions if mode=='definitions' else [], 'notice':notice}

    def get_entry(self, entry_id):
        with self.connect() as c:
            row=c.execute('SELECT * FROM entries WHERE id=?',(entry_id,)).fetchone()
            if row is None:
                raise KeyError('Entry not found')
            result=self.pack(row)
            result['headwords']=[r['headword'] for r in c.execute('SELECT headword FROM headwords WHERE entry_id=? AND sense_id IS NULL',(entry_id,))]
            result['senses']=[self.pack(r) for r in c.execute('SELECT * FROM senses WHERE entry_id=? ORDER BY rowid',(entry_id,))]
            result['references']=[dict(r) for r in c.execute('SELECT * FROM refs WHERE entry_id=?',(entry_id,))]
            for ref in result['references']:
                ref['targets']=[self.pack(r) for r in c.execute('''SELECT DISTINCT e.id,a.headword,e.pos,e.homonym,e.labels,a.sense_id
                    FROM headwords a JOIN entries e ON e.id=a.entry_id WHERE a.norm=? ORDER BY e.id LIMIT 12''',(ref['norm'],))]
            with self.corpus.open('rb') as f:
                f.seek(entry_id)
                raw=f.read(row['source_length']).decode('ascii')
            data=entry_data(raw,entry_id)
            result['etymologies']=[clean(n) for n in data['tree'].walk() if n.tag in {'et','etym'}]
            result['quotation_total']=c.execute('SELECT count(*) FROM quotations WHERE entry_id=?',(entry_id,)).fetchone()[0]
            result['quotations']=[r['text'] for r in c.execute('SELECT text FROM quotations WHERE entry_id=? LIMIT 40',(entry_id,))]
            result['source']={'corpus_offset':entry_id,'length':row['source_length'], 'sha256':row['source_sha256'],
                              'unmapped_entities':sorted(set(re.findall(r'⟦(&[^⟧]+)⟧',clean(data['tree']))))}
            return result

    def quotations(self, entry_id, offset=0):
        with self.connect() as c:
            if not c.execute('SELECT 1 FROM entries WHERE id=?',(entry_id,)).fetchone():
                raise KeyError('Entry not found')
            return {'quotations':[r['text'] for r in c.execute('SELECT text FROM quotations WHERE entry_id=? LIMIT 40 OFFSET ?',(entry_id,offset))]}

    def raw(self, entry_id):
        with self.connect() as c:
            row=c.execute('SELECT source_length FROM entries WHERE id=?',(entry_id,)).fetchone()
            if row is None:
                raise KeyError('Entry not found')
        with self.corpus.open('rb') as f:
            f.seek(entry_id)
            return f.read(row['source_length'])

    def related(self, entry_id, sense_id=None, obscure=False, literary=False):
        with self.connect() as c:
            entry=c.execute('SELECT * FROM entries WHERE id=?',(entry_id,)).fetchone()
            if entry is None:
                raise KeyError('Entry not found')
            if sense_id:
                sense=c.execute('SELECT * FROM senses WHERE id=? AND entry_id=?',(sense_id,entry_id)).fetchone()
                if sense is None:
                    raise KeyError('Sense not found in this entry')
            else:
                sense=c.execute('SELECT * FROM senses WHERE entry_id=? ORDER BY rowid LIMIT 1',(entry_id,)).fetchone()
            direct=[]
            if sense:
                refs=c.execute('''SELECT * FROM refs WHERE entry_id=? AND context!='quotation'
                                 AND (sense_id=? OR sense_id IS NULL)''',(entry_id,sense['id'])).fetchall()
                for ref in refs:
                    targets=c.execute('''SELECT DISTINCT e.id,a.headword,e.pos,e.homonym,e.labels,a.sense_id
                        FROM headwords a JOIN entries e ON e.id=a.entry_id WHERE a.norm=? AND e.id!=?
                        AND (?=0 OR EXISTS(SELECT 1 FROM senses s WHERE s.entry_id=e.id AND s.obscure=1))
                        AND (?=0 OR EXISTS(SELECT 1 FROM senses s WHERE s.entry_id=e.id AND s.literary=1))
                        LIMIT 6''',(ref['norm'],entry_id,int(obscure),int(literary))).fetchall()
                    direct.append({'target':ref['target'],'text':ref['text'],'context':ref['context'],
                                   'target_sense':ref['target_sense'],'targets':[self.pack(r) for r in targets],
                                   'connection':'Etymological reference' if ref['context']=='etymology' else 'Explicit dictionary reference'})
            incoming=[]
            for row in c.execute('''SELECT DISTINCT e.id,e.headword,e.pos,e.homonym,r.context,r.text
                    FROM refs r JOIN entries e ON e.id=r.entry_id
                    WHERE r.norm IN (SELECT norm FROM headwords WHERE entry_id=?) AND r.context!='quotation' AND e.id!=?
                    AND (?=0 OR EXISTS(SELECT 1 FROM senses s WHERE s.entry_id=e.id AND s.obscure=1))
                    AND (?=0 OR EXISTS(SELECT 1 FROM senses s WHERE s.entry_id=e.id AND s.literary=1))
                    LIMIT 25''',(entry_id,entry_id,int(obscure),int(literary))):
                incoming.append(dict(row))
            family=[self.pack(r) for r in c.execute('''SELECT s.*,e.pos,e.homonym FROM senses s
                    JOIN entries e ON e.id=s.entry_id WHERE s.entry_id=? AND s.tag='sub'
                    AND (? IS NULL OR s.id!=?) AND (?=0 OR s.obscure=1) AND (?=0 OR s.literary=1)
                    ORDER BY s.rowid LIMIT 24''',(entry_id,sense['id'] if sense else None,
                    sense['id'] if sense else None,int(obscure),int(literary)))]
            for item in family:
                item['connection']='Subentry grouped here by the dictionary'
            if not sense:
                return {'explicit':direct,'incoming':incoming,'family':family,'suggestions':[],'terms':[]}
            counts=Counter(w for w in words(sense['definition']) if w not in STOP and len(w)>3)
            # Global term frequency selects informative words. Unknown Porter
            # forms get a neutral prior rather than being treated as unique.
            total=c.execute("SELECT value FROM metadata WHERE key='senses'").fetchone()
            total=int(total[0]) if total else 1
            scored=[]
            import math
            for term,count in counts.most_common(60):
                df=c.execute('SELECT doc FROM terms WHERE term=?',(term,)).fetchone()
                frequency=df[0] if df else max(100,total//100)
                if frequency > max(100,total//10):
                    continue
                scored.append((count*math.log(1+total/frequency),term))
            tokens=[t for _,t in sorted(scored,reverse=True)[:14]]
            match=' OR '.join('"'+w+'"' for w in tokens)
            suggestions=[]
            if match:
                rows=c.execute('''SELECT s.*,e.pos,e.homonym,bm25(definitions,1.0,0.0,0.0) AS score
                    FROM definitions JOIN senses s ON s.rowid=definitions.rowid
                    JOIN entries e ON e.id=s.entry_id
                    WHERE definitions MATCH ? AND s.entry_id!=?
                    AND (?=0 OR s.obscure=1) AND (?=0 OR s.literary=1)
                    ORDER BY score LIMIT 180''',(match,entry_id,int(obscure),int(literary))).fetchall()
                seen=set()
                for row in rows:
                    if row['entry_id'] in seen:
                        continue
                    d=self.pack(row)
                    evidence=[w for w in tokens if re.search(r'\b'+re.escape(w)+r'\b',d['definition'],re.I)]
                    d['matched_terms']=evidence
                    d['connection']='Inferred definition similarity'
                    d['explanation']='Shares definition terms: '+', '.join(evidence) if evidence else 'Shares indexed word stems with this sense'
                    suggestions.append(d)
                    seen.add(row['entry_id'])
                    if len(suggestions)==24:
                        break
            return {'selected_sense':sense['id'],'explicit':direct,'incoming':incoming,
                    'family':family,'suggestions':suggestions,'terms':tokens,
                    'notice':'Definition similarity is a discovery aid, not proof of synonymy. Incoming references may concern another homonym or sense.'}
