import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from oed.advanced import analyse,forms,categories,build as advanced_build
from oed.importer import build
from oed.service import Dictionary

DATA=b'''<e><hg><hw>cat</hw><pr><ph>k&t</ph></pr><ps>n.</ps></hg><s4>A feline animal.</s4><db><sub><bl>catty</bl><ps>a.</ps>Feline and spiteful.</sub></db></e>
<e><hg><hw>bat</hw><pr><ph>b&t</ph></pr><ps>n.</ps></hg><s4>A flying mammal.</s4></e>
<e><hg><hw>mat</hw><pr><ph>m&t</ph></pr><ps>v.</ps></hg><s4>To tangle fibres.</s4></e>
<e><hg><hw>dog</hw><pr><ph>dQg</ph></pr><ps>n.</ps></hg><s4>A canine animal.</s4></e>
<e><hg><hw>light</hw><pr><ph>laIt</ph></pr><ps>n.</ps></hg><s4>Illumination.</s4></e>
<e><hg><hw>night</hw><pr><ph>naIt</ph></pr><ps>n.</ps></hg><s4>The dark period.</s4></e>
<e><hg><hw>nation</hw><pr><ph>"neIS@n</ph></pr><ps>n.</ps></hg><s4>A people.</s4></e>
<e><hg><hw>station</hw><pr><ph>"steIS@n</ph></pr><ps>n.</ps></hg><s4>A stopping place.</s4></e>
<e><hg><hw>late</hw><pr><ph>leIt</ph></pr><ps>a.</ps></hg><s4>After the time.</s4></e>
<e><hg><hw>reed</hw><pr><ph>ri:d</ph></pr><ps>n.</ps></hg><s4>A plant.</s4></e>
<e><hg><hw>red</hw><pr><ph>rEd</ph></pr><ps>a.</ps></hg><s4>A colour.</s4></e>
<e><hg><hw>read</hw><pr><ph>ri:d</ph></pr><ps>v.</ps></hg><s4>To interpret writing.</s4></e>
<e><hg><hw>read</hw><pr><ph>rEd</ph></pr><ps>ppl. a.</ps></hg><s4>Interpreted.</s4></e>
<e st=obs><hg><hw>gnat</hw><pr><ph>n&t</ph></pr><ps>n.</ps></hg><la>Poet.</la><s4>A small insect.</s4></e>
<e><hg><hw>bat</hw><pr><ph>b&t</ph></pr><ps>n.</ps></hg><s4>A wooden striking implement.</s4></e>
<e><hg><hw>shoe</hw><pr><ph>Su:</ph></pr><ps>n.</ps></hg><s4>A covering for the foot.</s4></e>
<e><hg><hw>Q</hw><pr><ph>kju:</ph></pr></hg><s4>A letter of the alphabet.</s4></e>
<e><hg><hw>cue</hw><pr><ph>kju:</ph></pr><ps>n.</ps></hg><s4>A signal to begin speaking.</s4></e>
<e st=obs><hg><hw>bow</hw><pr><ph>bu:</ph></pr><ps>n.</ps></hg><la>north. dial.</la><s4>A stock of cattle on a farm.</s4></e>
<e><hg><hw>unknown</hw></hg><s4>Unlabelled.</s4></e>'''

class AdvancedTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();root=Path(cls.temp.name)
        corpus=root/'corpus.sgml';corpus.write_bytes(DATA)
        (root/'extraction.json').write_text(json.dumps({'corpus_sha256':hashlib.sha256(DATA).hexdigest(),'database_sha1':'fixture'}))
        database=root/'oed.sqlite'
        with contextlib.redirect_stdout(io.StringIO()):
            build(corpus,database);advanced_build(database,corpus,root/'advanced.sqlite')
        cls.dictionary=Dictionary(database,corpus)
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def names(self,r):return {x['headword'] for x in r['results']}
    def test_exact_rhyme_finite_oracle(self):
        expected={'cat':{'bat','mat','gnat'},'light':{'night'},'nation':{'station'}}
        for word,names in expected.items():
            with self.subTest(word=word):self.assertEqual(self.names(self.dictionary.search(word,'rhyme')),names)
    def test_grouped_rhyme_paging_and_evidence(self):
        result=self.dictionary.search('cat','rhyme')
        self.assertEqual(result['total'],3)
        bat=next(x for x in result['results'] if x['headword']=='bat')
        self.assertEqual(bat['entry_count'],2)
        self.assertEqual(len(bat['variants']),2)
        pages=[self.dictionary.search('cat','rhyme',limit=1,offset=i) for i in range(3)]
        self.assertEqual({p['results'][0]['headword'] for p in pages},{'bat','gnat','mat'})
        self.assertEqual([p['next_offset'] for p in pages],[1,2,None])
        self.assertFalse(self.dictionary.search('cat','rhyme',offset=20)['results'])
        with self.assertRaises(ValueError):self.dictionary.search('cat','rhyme',offset=-1)
        shoe=self.dictionary.search('shoe','rhyme')
        q=next(x for x in shoe['results'] if x['headword']=='Q')
        self.assertEqual(q['phonetic_match']['homophone'],'cue')
        self.assertEqual(q['phonetic_match']['ending'],'uː')
        self.assertEqual(shoe['sound_summary']['ending_hint'],'long “oo” sound')
        bow=next(x for x in shoe['results'] if x['headword']=='bow')
        self.assertIn('Obsolete',bow['usage_labels'])
        self.assertIn('Northern dialect',bow['usage_labels'])
        self.assertIn('cattle',bow['definition'])

    def test_pos_and_combined_usage_filters(self):
        self.assertEqual(self.names(self.dictionary.search('cat','rhyme',pos='verb')),{'mat'})
        self.assertEqual(self.names(self.dictionary.search('cat','rhyme',pos='noun',obscure=True,literary=True)),{'gnat'})
        self.assertFalse(self.dictionary.search('catty',pos='noun')['results'])
        self.assertEqual(self.dictionary.search('catty',pos='adjective')['results'][0]['pos'],'a.')
        self.assertTrue(self.dictionary.search('unknown',pos='unlabelled')['results'])
        self.assertFalse(self.dictionary.search('unknown',pos='noun')['results'])
    def test_definition_and_quotation_filter_contract(self):
        self.assertTrue(self.dictionary.search('feline','definitions',pos='adjective')['results'])
        self.assertFalse(self.dictionary.search('feline','definitions',pos='verb')['results'])
        self.assertFalse(self.dictionary.search('feline','quotations',pos='verb')['results'])
    def test_syllables_and_recorded_stress(self):
        self.assertEqual(self.names(self.dictionary.search('nation','rhyme',syllables=2,stress='10')),{'station'})
        self.assertFalse(self.dictionary.search('nation','rhyme',syllables=1)['results'])
        self.assertEqual(analyse('ˈneɪʃən')['stress'],'10')
        self.assertIsNone(analyse('neɪʃən')['rhyme'])
        self.assertEqual(analyse('ã')['syllables'],1)
    def test_pronunciation_choice_required(self):
        r=self.dictionary.search('read','rhyme');self.assertTrue(r['needs_pronunciation'])
        self.assertEqual(len(r['pronunciations']),2)
        for ipa,target in [('riːd','reed'),('rɛd','red')]:
            key=next(o['key'] for o in r['pronunciations'] if o['ipa']==ipa)
            self.assertIn(target,self.names(self.dictionary.search('read','rhyme',pronunciation=key)))
        with self.assertRaises(ValueError):self.dictionary.search('read','rhyme',pronunciation='wrong')
    def test_ipa_and_approximate_matching(self):
        self.assertEqual(self.names(self.dictionary.search('/kæt/','rhyme',input_type='ipa')),{'cat','bat','mat','gnat'})
        self.assertIn('late',self.names(self.dictionary.search('light','near-rhyme')))
        self.assertNotIn('night',self.names(self.dictionary.search('light','near-rhyme')))
        self.assertIn('bat',self.names(self.dictionary.search('cat','sounds-like')))
        self.assertTrue(all('Approximate' in x['connection'] for x in self.dictionary.search('cat','sounds-like')['results']))
    def test_missing_and_invalid_pronunciations(self):
        self.assertFalse(self.dictionary.search('unknown','rhyme')['results'])
        for value in ['see below','formerly ˈreɪʃən','Stress variable.','abc123','ˈ','','-laɪt','laɪt-']:
            with self.subTest(value=value),self.assertRaises(ValueError):analyse(value)
        with self.assertRaises(ValueError):self.dictionary.search('cat','rhyme',stress='xyz')
        with self.assertRaises(ValueError):self.dictionary.search('cat','rhyme',syllables=0)
        with self.assertRaises(ValueError):self.dictionary.search('cat',pos='alien')
    def test_optional_rhotic_and_grammar_categories(self):
        parsed,errors=forms('kɑː(r)');self.assertFalse(errors)
        self.assertEqual({p['ipa'] for p in parsed},{'kɑː','kɑːr'})
        self.assertEqual(set(categories('a. and n.')),{'adjective','noun'})
        self.assertNotIn('verb',categories('adv.'))
        self.assertNotIn('adjective',categories('pa. pple.'))
        self.assertIn('adjective',categories('adjs.'))

if __name__=='__main__':unittest.main()
