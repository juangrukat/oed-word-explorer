"""Phonetic search over recorded pronunciations in the auxiliary index."""
import json
import re
from .advanced import analyse, SOUND_MODES
from .markup import normalize


def sound_search(dictionary,query,mode,pos,obscure,literary,syllables,stress,pronunciation,input_type,limit):
    if mode not in SOUND_MODES:raise ValueError('Invalid sound-search mode')
    if input_type not in {'word','ipa'}:raise ValueError('Choose word or IPA input')
    with dictionary.connect() as c:
        if not dictionary.advanced_path.exists():raise ValueError('Sound index is missing; run python3 -m oed.advanced')
        options=[]
        if input_type=='ipa':
            selected=analyse(query)
        else:
            options=[dict(r) for r in c.execute('''SELECT DISTINCT p.ipa,p.key,p.rhyme,p.tail,p.syllables,p.stress,p.recorded
                FROM headwords a JOIN advanced.sounds p ON p.entry_id=a.entry_id
                WHERE a.norm=? AND a.sense_id IS NULL ORDER BY p.key''',(normalize(query),))]
            if not options:
                return {'query':query,'mode':mode,'results':[], 'notice':'No usable recorded pronunciation for this exact headword. Try another word or enter IPA.','pronunciations':[]}
            if pronunciation:
                chosen=next((o for o in options if o['key']==pronunciation),None)
                if chosen is None:raise ValueError('Selected pronunciation is not recorded for this headword')
                selected=chosen
            elif len(options)>1:
                return {'query':query,'mode':mode,'results':[], 'pronunciations':options,
                        'needs_pronunciation':True,'notice':'Choose which recorded pronunciation to explore.'}
            else:selected=options[0]
        if mode=='rhyme' and not selected['rhyme']:
            return {'query':query,'mode':mode,'results':[],'pronunciations':options,
                    'notice':'This multisyllabic pronunciation has no usable recorded main stress. Choose near rhymes or similar pronunciation.'}
        if mode=='rhyme':
            scores={selected['rhyme']:0.};column='rhyme'
        else:
            column='near_key' if mode=='near-rhyme' else 'key'
            key=(selected['rhyme'] or selected['tail']) if mode=='near-rhyme' else selected['key']
            scores=dict((key,score) for score,key in dictionary.sound_index.nearest(key,mode))
        if not scores:return {'query':query,'mode':mode,'results':[],'pronunciations':options,'notice':'No close recorded sounds found.'}
        c.execute('PRAGMA temp_store=MEMORY')
        c.execute('CREATE TEMP TABLE sound_candidates(key TEXT PRIMARY KEY,score REAL)')
        c.executemany('INSERT INTO sound_candidates VALUES(?,?)',scores.items())
        pos_clause=dictionary.pos_clause('e.id',"''",pos)
        expression='coalesce(p.rhyme,p.tail)' if column=='near_key' else 'p.'+column
        rows=c.execute('''SELECT e.id,e.headword,e.pos,e.homonym,e.labels,p.ipa,p.recorded,p.optional,p.key,p.rhyme,p.tail,p.syllables,p.stress,
            coalesce(p.rhyme,p.tail) AS near_key,MIN(candidates.score) AS candidate_score
            FROM advanced.sounds p JOIN sound_candidates candidates ON candidates.key='''+expression+'''
            JOIN entries e ON e.id=p.entry_id
            WHERE (?=0 OR EXISTS(SELECT 1 FROM senses s WHERE s.entry_id=e.id AND s.obscure=1))
            AND (?=0 OR EXISTS(SELECT 1 FROM senses s WHERE s.entry_id=e.id AND s.literary=1))
            AND (? IS NULL OR p.syllables=?) AND (?='' OR p.stress GLOB ?)
            AND (?=0 OR candidates.score>0) AND (?='' OR e.norm!=?)
            '''+pos_clause+''' GROUP BY e.id
            ORDER BY candidate_score,length(e.norm),e.norm,e.id LIMIT ?''',
            (int(obscure),int(literary),syllables,syllables,stress,stress,
             int(mode=='near-rhyme'),normalize(query) if input_type=='word' else '',normalize(query),
             *((pos,) if pos!='any' else ()),limit)).fetchall()
        selected_tokens=selected['key']
        ranked=[]
        for row in rows:
            if input_type=='word' and normalize(row['headword'])==normalize(query):continue
            if mode=='near-rhyme' and scores[row[column]]==0:continue
            if stress and (row['stress'] is None or not re.fullmatch(stress.replace('?','.'),row['stress'])):continue
            item=dictionary.pack(row)
            item['sound_score']=scores[row[column]]
            item['phonetic_match']={'ipa':row['ipa'],'recorded':row['recorded'],'optional':bool(row['optional']),
                                     'syllables':row['syllables'],'stress':row['stress'],'rhyming_ending':row['rhyme']}
            item['connection']={'rhyme':'Exact recorded rhyme','near-rhyme':'Approximate near rhyme','sounds-like':'Approximate pronunciation similarity'}[mode]
            item['explanation']=('Same stressed vowel and ending: /'+row['rhyme'].replace(' ','')+'/' if mode=='rhyme' else
                                  'Similar ending: /'+(row['rhyme'] or row['tail']).replace(' ','')+'/' if mode=='near-rhyme' else
                                  'Similar recorded sounds to /'+selected['ipa']+'/')
            s=c.execute('SELECT definition FROM senses WHERE entry_id=? ORDER BY rowid LIMIT 1',(row['id'],)).fetchone()
            item['definition']=s['definition'] if s else ''
            ranked.append(item)
        ranked.sort(key=lambda r:(r['sound_score'],len(normalize(r['headword'])),normalize(r['headword']),r['id']))
        results=[];seen=set()
        for item in ranked:
            if item['id'] in seen:continue
            seen.add(item['id']);results.append(item)
            if len(results)>=limit:break
        return {'query':query,'mode':mode,'results':results,'pronunciations':options,'selected_pronunciation':selected,
                'notice':'Matches use recorded pronunciations. Syllable counts are estimated from vowel nuclei; near/similar matches are approximate. Unrecorded pronunciations are excluded.'}
