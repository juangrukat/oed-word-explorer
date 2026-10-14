import contextlib
import hashlib
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.request import urlopen
from urllib.error import HTTPError
from oed.importer import build
from oed.markup import entry_data, clean, parse
from oed.server import handler
from oed.service import Dictionary

CORPUS = b'''<e><hg><hw>lament</hw><ps>v.</ps></hg><etym>From <xr><x>lamentum</x></xr>.</etym><s4 num=1>To express grief and sorrow.<xr><x>threnody</x></xr><s6 num=a>To mourn a death.</s6></s4><qp><q><qd>1600</qd><qt>The unicorn was silent.</qt></q></qp><db><sub><bl>lamentful</bl><la>rare</la>Full of grief and sorrow.</sub></db></e>
<e st=obs><hg><hw>threnody</hw><ps>n.</ps></hg><s4>A poem of mourning, a song of grief.</s4></e>
<e><hg><hw>elegy</hw><ps>n.</ps></hg><s4>A poem of mourning for the dead.</s4></e>
<e><hg><hw>litotes</hw></hg><la>Rhet.</la><s4>An affirmative expressed by the negative of the contrary.</s4></e>
<ve><hg><hw>lamentum</hw><hw>lamentume</hw></hg>See <xr><x>lament</x></xr>.</ve>
<e><hg><hw>poem</hw></hg><s4>A metrical work in verse; a piece of poetry.</s4></e>
<e><hg><hw>mourning</hw></hg><s4>Grief, sorrow, lamentation.</s4></e>
<e><hg><hw>dirge</hw></hg><s4>A form of verse.</s4><s4>A song of lamentation.</s4></e>'''

class DictionaryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        root=Path(cls.temp.name)
        cls.corpus=root/'corpus.sgml';cls.corpus.write_bytes(CORPUS)
        (root/'extraction.json').write_text(json.dumps({'corpus_sha256':hashlib.sha256(CORPUS).hexdigest(),'database_sha1':'fixture'}))
        cls.database=root/'oed.sqlite'
        with contextlib.redirect_stdout(io.StringIO()):
            build(cls.corpus,cls.database)
        cls.dictionary=Dictionary(cls.database,cls.corpus)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_definition_search_excludes_quotations(self):
        self.assertEqual(self.dictionary.search('unicorn','definitions')['results'],[])
        self.assertEqual(self.dictionary.search('unicorn','quotations')['results'][0]['headword'],'lament')

    def test_sense_hierarchy_and_raw_provenance(self):
        d=self.dictionary.get_entry(0)
        self.assertEqual(d['pos'],'v.')
        self.assertEqual(len(d['senses']),3)
        self.assertEqual(d['senses'][1]['parent_id'],d['senses'][0]['id'])
        self.assertEqual(d['senses'][2]['headword'],'lamentful')
        self.assertEqual(hashlib.sha256(self.dictionary.raw(0)).hexdigest(),d['source']['sha256'])
        self.assertIn('unicorn',d['quotations'][0])

    def test_alias_and_subentry_search(self):
        alias=self.dictionary.search('lamentume')['results'][0]
        self.assertEqual(alias['headword'],'lamentume')
        sub=self.dictionary.search('lamentful')['results'][0]
        self.assertEqual(sub['id'],0)
        self.assertTrue(sub['matched_sense_id'])
        self.assertEqual(self.dictionary.search('lam?nt*')['results'][0]['id'],0)

    def test_star_survives_normalization_and_matches_internal_sequences(self):
        self.assertIn('lamentful',[x['headword'] for x in self.dictionary.search('la*ful')['results']])
        self.assertIn('lamentful',[x['headword'] for x in self.dictionary.search('lam?nt*')['results']])
        self.assertEqual(self.dictionary.search('la?ent')['results'][0]['headword'],'lament')

    def test_explicit_and_inferred_connections(self):
        d=self.dictionary.get_entry(0)
        r=self.dictionary.related(0,d['senses'][0]['id'],obscure=True)
        self.assertTrue(any(x['target']=='threnody' and x['targets'] for x in r['explicit']))
        self.assertTrue(any(x['headword']=='threnody' for x in r['suggestions']))
        self.assertEqual(r['family'][0]['headword'],'lamentful')
        self.assertNotIn('unicorn',r['terms'])
        with self.assertRaises(KeyError):
            self.dictionary.related(0,'wrong:0')

    def test_literary_labels_and_obsolete_filters(self):
        results=self.dictionary.search('litotes',literary=True)['results']
        self.assertEqual(results[0]['headword'],'litotes')
        self.assertEqual(self.dictionary.search('elegy',obscure=True)['results'],[])
        self.assertEqual(self.dictionary.search('threnody',obscure=True)['results'][0]['headword'],'threnody')

    def test_idea_expansion_returns_source_and_supporting_senses(self):
        result=self.dictionary.search('poem mourning','definitions')
        self.assertTrue(result['expansions'])
        self.assertTrue(all(x['definition'] and x['entry_id'] is not None for x in result['expansions']))
        dirge=next(x for x in result['results'] if x['headword']=='dirge')
        self.assertTrue(dirge['supporting_senses'])
        self.assertIn('different senses',result['notice'])

    def test_legacy_characters_and_phonetics(self):
        tree,issues=parse('<e><hg><hw>th&amac.t</hw><pr><ph>"T&t</ph></pr></hg><s4>&mystery.Symbol.</s4></e>')
        self.assertFalse(issues)
        self.assertIn('thāt',clean(tree))
        self.assertIn('ˈθæt',clean(tree))
        self.assertIn('⟦&mystery.⟧',clean(tree))

    def test_variant_labels_do_not_classify_all_senses(self):
        d=entry_data('<e><hg><hw>dirge</hw><ps>n.</ps></hg><vfl><la>Sc.</la>dergie</vfl><s4>A song of mourning.</s4></e>',0)
        self.assertEqual(d['labels'],[])
        self.assertEqual(d['senses'][0]['labels'],[])

    def test_homonyms_are_not_lookup_digits_or_etymology_grammar(self):
        d=entry_data('<e><hg><hw>ruth<su>1</su></hw><ps>n.</ps></hg><etym>From <xr><x>word</x><ps>v.</ps></xr></etym><s4>Sorrow.</s4></e>',0)
        self.assertEqual(d['headword'],'ruth')
        self.assertEqual(d['homonym'],'1')
        self.assertEqual(d['pos'],'n.')
        self.assertEqual(entry_data('<e><hg><hw>A1</hw></hg><s4>A class.</s4></e>',0)['norm'],'a1')

    def test_http_contract_and_file_boundary(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),handler(self.dictionary))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            with urlopen(base+'/api/entry?id=0') as r:
                self.assertEqual(json.load(r)['headword'],'lament')
                self.assertEqual(r.headers['X-Content-Type-Options'],'nosniff')
            for path,code in [('/api/entry?id=999999',404),('/api/entry?id=invalid',400),('/api/search?mode=bad&q=word',400),('/../data/corpus.sgml',404)]:
                with self.assertRaises(HTTPError) as caught:
                    urlopen(base+path)
                self.assertEqual(caught.exception.code,code)
                caught.exception.close()
        finally:
            server.shutdown();server.server_close();thread.join()

if __name__=='__main__':
    unittest.main()
