"""Focused synthetic checks for auxiliary-only English timing extraction."""
import unittest

from english_timing import english_timing_labels


class Processor:
    words={'chatgpt':[1,2],'oracle':[3],'dsh':[4]}
    def encode(self,text):return self.words.get(text,[0])
    def decode(self,ids):return next((w for w,t in self.words.items() if t==ids),'?')
    def id_to_piece(self,i):return {1:'▁chat',2:'gpt',3:'▁oracle',4:'▁dsh'}.get(i,'?')


class EnglishTimingTest(unittest.TestCase):
    def test_cyrillic_not_sent_to_russian_head(self):
        labels,words=english_timing_labels('ещё ёж 17 ChatGPT',Processor(),'lower')
        self.assertEqual(labels,[('rus',None)]*3+[('eng',1),('eng',2)])
        self.assertTrue(all(w.get('acoustic_token_ids') is None for w in words[:3]))

    def test_phrase_separator_and_punctuation(self):
        labels,_=english_timing_labels('ChatGPT Oracle, затем DSH.',Processor(),'lower')
        self.assertEqual(labels,[('eng',1),('eng',2),('eng',3),('rus',None),('eng',4)])

    def test_all_russian_no_english_phrase(self):
        labels,_=english_timing_labels('ещё раз попробуй',Processor(),'lower')
        self.assertEqual(labels,[('rus',None)]*3)

    def test_unsupported_words_not_silently_reclassified(self):
        for text in ('žaba','3D','neologism','中','русEN'):
            with self.subTest(text=text),self.assertRaises(ValueError):english_timing_labels(text,Processor(),'lower')

    def test_empty_and_unknown_are_not_labels(self):
        with self.assertRaises(ValueError):english_timing_labels('!!!',Processor())
        with self.assertRaises(ValueError):english_timing_labels('Unknown',Processor())


if __name__=='__main__':unittest.main()
