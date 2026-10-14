"""Phonetic search over recorded pronunciations in the auxiliary index."""
import json
from .advanced import analyse, SOUND_MODES
from .markup import normalize


def sound_search(dictionary,query,mode,pos,obscure,literary,syllables,stress,pronunciation,input_type,limit,offset=0):
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
        sound_index={'rhyme':'sounds_rhyme','near_key':'sounds_near','key':'sounds_key'}[column]
        # Candidates must drive the lookup, before any correlated usage checks.
        rows=c.execute('''SELECT e.id,e.headword,e.norm,e.pos,e.homonym,e.labels,p.ipa,p.recorded,p.optional,p.key,p.rhyme,p.tail,p.syllables,p.stress,
            coalesce(p.rhyme,p.tail) AS near_key,candidates.score AS candidate_score
            FROM sound_candidates candidates CROSS JOIN advanced.sounds p INDEXED BY '''+sound_index+'''
            CROSS JOIN entries e
            WHERE candidates.key='''+expression+''' AND e.id=p.entry_id AND (?=0 OR EXISTS(SELECT 1 FROM senses s INDEXED BY senses_entry WHERE s.entry_id=e.id AND s.obscure=1))
            AND (?=0 OR EXISTS(SELECT 1 FROM senses s INDEXED BY senses_entry WHERE s.entry_id=e.id AND s.literary=1))
            AND (? IS NULL OR p.syllables=?) AND (?='' OR p.stress GLOB ?)
            AND (?=0 OR candidates.score>0) AND (?='' OR e.norm!=?)
            '''+pos_clause+''' ORDER BY candidates.score,e.norm,e.id,p.key''',
            (int(obscure),int(literary),syllables,syllables,stress,stress,
             int(mode=='near-rhyme'),normalize(query) if input_type=='word' else '',normalize(query),
             *((pos,) if pos!='any' else ()))).fetchall()
        groups={}
        for row in rows:
            groups.setdefault(row['norm'],[]).append(row)
        ordered=sorted(groups.values(),key=lambda group:(group[0]['candidate_score'],group[0]['norm']))
        results=[]
        for group in ordered[offset:offset+limit]:
            variants=[]
            for row in group:
                item=dictionary.pack(row)
                item['sound_score']=row['candidate_score']
                ending=row['rhyme'] or row['tail']
                item['phonetic_match']={'ipa':row['ipa'],'recorded':row['recorded'],'optional':bool(row['optional']),
                    'syllables':row['syllables'],'stress':row['stress'],'rhyming_ending':row['rhyme'],
                    'ending':ending.replace(' ',''),'ending_hint':ending_hint(ending),
                    'homophone':homophone(c,row['key'],row['norm'])}
                item['connection']={'rhyme':'Exact recorded rhyme','near-rhyme':'Approximate near rhyme','sounds-like':'Approximate pronunciation similarity'}[mode]
                item['explanation']=('Shares the stressed vowel and all following sounds with the selected pronunciation.' if mode=='rhyme' else
                    'A similar ending, not an exact rhyme.' if mode=='near-rhyme' else 'Similar whole-word sounds; this is not necessarily a rhyme.')
                item['usage_labels']=list(dict.fromkeys(expand_label(x) for x in item['labels'] if not x.startswith('Status:')))
                definitions=c.execute('SELECT definition FROM senses WHERE entry_id=? ORDER BY rowid LIMIT 20',(row['id'],)).fetchall()
                useful=next((x['definition'] for x in definitions if len(x['definition'])>=30 and x['definition'].strip().lower() not in {'inflexional forms.','properly.'}),None)
                item['definition']=useful or (definitions[0]['definition'] if definitions else '')
                variants.append(item)
            representative=dict(variants[0]);representative['variants']=variants
            representative['entry_count']=len({x['id'] for x in variants})
            results.append(representative)
        return {'query':query,'mode':mode,'results':results,'pronunciations':options,'selected_pronunciation':selected,
                'sound_summary':{'ending':(selected['rhyme'] or selected['tail']).replace(' ',''),
                                 'ending_hint':ending_hint(selected['rhyme'] or selected['tail'])},
                'total':len(ordered),'offset':offset,'next_offset':offset+len(results) if offset+len(results)<len(ordered) else None,
                'notice':'All matching historical, dialectal and obscure entries remain included. Usage and meaning refer to the linked dictionary entry; labels can apply to particular senses. Pronunciations are recorded, not generated. Approximate searches use a bounded candidate set.'}


ENDING_HINTS={'uː':'long “oo” sound','iː':'long “ee” sound','æ':'vowel sound in “cat”',
              'aɪ':'vowel sound in “eye”','eɪ':'vowel sound in “day”','əʊ':'vowel sound in “go”',
              'ɔɪ':'vowel sound in “boy”','aʊ':'vowel sound in “now”'}
FAMILIAR=('cue','boo','blue','do','too','two','you','new','true','shoe','coo','moo','who','zoo',
          'red','reed','see','sea','bee','be','eye','day','go','boy','now','cat','night','light')
LABELS={'obs.':'Obsolete','obsolete':'Obsolete','dial.':'Dialectal','north. dial.':'Northern dialect',
        'sc.':'Scottish','arch.':'Archaic','rare':'Rare','rare.':'Rare','poet.':'Poetic',
        'slang.':'Slang','colloq.':'Colloquial','u.s.':'United States','hist.':'Historical'}

def expand_label(label):
    return LABELS.get(label.lower(),label)

def ending_hint(ending):
    return ENDING_HINTS.get(ending,'')

def homophone(connection,key,exclude):
    # Examples are selected from a small readable vocabulary, but equality must
    # be established from indexed pronunciations. Never invent respellings.
    rows=connection.execute('''SELECT DISTINCT e.norm,e.headword FROM advanced.sounds p
        JOIN entries e ON e.id=p.entry_id WHERE p.key=? AND e.norm IN ('''+','.join('?' for _ in FAMILIAR)+')',
        (key,*FAMILIAR)).fetchall()
    choices={r['norm']:r['headword'] for r in rows if r['norm']!=exclude}
    return next((choices[w] for w in FAMILIAR if w in choices),None)
