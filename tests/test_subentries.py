import unittest
from oed.markup import entry_data
from oed.subentries import contexts


class SubentryTest(unittest.TestCase):
    def context(self,raw):
        data=entry_data(raw,100)
        return list(contexts(data['tree'],data['senses']).values())

    def test_undefined_derivative_with_following_source_quote(self):
        result=self.context('<e><hg><hw>bowl</hw></hg><s4>A vessel for food.</s4><db>Hence <sub><bl>bowlful</bl>.</sub></db><qp><q><qd>1904</qd> <qt>Half a bowlful of water.</qt></q><q><qt>A dish of soup.</qt></q></qp></e>')[0]
        self.assertTrue(result['definition_missing'])
        self.assertEqual(result['parent_definition'],'A vessel for food.')
        self.assertEqual(result['quotations'],['1904 Half a bowlful of water.'])

    def test_multiple_subentries_only_receive_their_own_examples(self):
        results=self.context('<e><hg><hw>bowl</hw></hg><s4>A vessel.</s4><db><sub><bl>bowlful</bl>.</sub><sub><bl>bowlish</bl>Resembling a bowl.<qp><q><qt>A bowlish shape.</qt></q></qp></sub></db><qp><q><qt>A bowlful of soup.</qt></q><q><qt>A bowlfulness unknown.</qt></q></qp><s4>Another meaning.</s4><qp><q><qt>A bowlful elsewhere.</qt></q></qp></e>')
        self.assertEqual(results[0]['quotations'],['A bowlful of soup.'])
        self.assertFalse(results[1]['definition_missing'])
        self.assertEqual(results[1]['quotations'],['A bowlish shape.'])

    def test_parent_sense_and_missing_examples(self):
        result=self.context('<e><hg><hw>bowl</hw></hg><s4>A vessel.</s4><s4>A game.<sub><bl>bowler</bl>A player.</sub></s4></e>')[0]
        self.assertEqual(result['parent_definition'],'A game.')
        self.assertEqual(result['quotations'],[])

if __name__=='__main__':unittest.main()
