import unittest
from dbg3k.commands import select_thread_id, locals_request
from dbg3k.mi import parse_record

class ThreadWatchTests(unittest.TestCase):
    def test_gdb_example_command(self):
        self.assertEqual(locals_request('1', 0),
                         '-stack-list-variables --thread 1 --frame 0 --all-values')

    def test_get_current_thread(self):
        line = '4^done,threads=[{id="2",state="stopped"},{id="5",state="stopped"}],current-thread-id="5"'
        payload = parse_record(line).payload
        self.assertEqual(select_thread_id(payload), '5')
        self.assertEqual(locals_request(select_thread_id(payload), 1),
                         '-stack-list-variables --thread 5 --frame 1 --all-values')

    def test_fallback_stopped_thread(self):
        self.assertEqual(select_thread_id({'threads': [
            {'id': '3', 'state': 'running'}, {'id': '4', 'state': 'stopped'}]}), '4')

    def test_no_thread_reported(self):
        self.assertIsNone(select_thread_id({'threads': []}))
        for value in ('all', '', '-1', '1;bad', None):
            with self.assertRaises(ValueError):
                locals_request(value, 0)

    def test_reject_invalid_frame(self):
        with self.assertRaises(ValueError):
            locals_request('1', -1)
