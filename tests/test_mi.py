import unittest
from dbg3k.mi import parse_record, MIParseError

class MIParserTests(unittest.TestCase):
    def test_stopped(self):
        r = parse_record('*stopped,reason="end-stepping-range",frame={addr="0x10000010",func="main",fullname="/tmp/main.c",line="23"},thread-id="1"')
        self.assertEqual(r.cls, 'stopped')
        self.assertEqual(r.payload['frame']['line'], '23')

    def test_nested_stack(self):
        r = parse_record('12^done,stack=[frame={level="0",func="foo"},frame={level="1",func="main"}]')
        self.assertEqual(r.token, 12)
        self.assertEqual(r.payload['stack'][1]['frame']['func'], 'main')

    def test_variables(self):
        r = parse_record('13^done,variables=[{name="n",type="int",value="12"},{name="s",value="\\"hi\\""}]')
        self.assertEqual(r.payload['variables'][0]['value'], '12')
        self.assertEqual(r.payload['variables'][1]['value'], '"hi"')

    def test_stream_and_prompt(self):
        self.assertEqual(parse_record('~"Hello\\n"').payload, 'Hello\n')
        self.assertIsNone(parse_record('(gdb)'))

    def test_error(self):
        self.assertEqual(parse_record('42^error,msg="No symbol"').payload['msg'], 'No symbol')
        with self.assertRaises(MIParseError):
            parse_record('^done,frame={broken')
