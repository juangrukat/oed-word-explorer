import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'research'))
from probe_database import decode, BLOCK

class DecoderTest(unittest.TestCase):
    @unittest.skipUnless(Path('/Volumes/OED2/OED2.DAT').exists(), 'source disc not mounted')
    def test_physical_block_end(self):
        with open('/Volumes/OED2/OED2.DAT', 'rb') as f:
            for index,end in [(214,b'<w>Burlington '),(449,b'esp. to prevent or disrupt '),(3578,b'<q><qd>')]:
                with self.subTest(block=index):
                    f.seek(0x16709000 + index * BLOCK)
                    text, number, span = decode(f.read(BLOCK))
                    self.assertTrue(text.endswith(end))
                    self.assertGreater(number,0)
                    self.assertGreater(span,0)
