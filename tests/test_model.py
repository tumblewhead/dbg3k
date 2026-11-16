import unittest
from dbg3k.model import Frame, ScopeModel, sparkline, number_of

class ScopeTests(unittest.TestCase):
    def test_numeric_and_sparkline(self):
        self.assertEqual(number_of('0x10'), 16)
        self.assertIsNone(number_of('0x10', 'void *'))
        self.assertEqual(sparkline([1, 2, 3]), '▁▅█')

    def test_shadowed_names_do_not_collide(self):
        model = ScopeModel()
        model.begin_stop()
        model.set_frames([Frame(0, 'foo', 'a.c', 8), Frame(1, 'bar', 'b.c', 5)])
        model.set_variables(0, [{'name': 'n', 'value': '1'}])
        model.set_variables(1, [{'name': 'n', 'value': '7'}])
        self.assertEqual({w.label for w in model.active_watches()}, {'foo.n', 'bar.n'})
        model.begin_stop()
        model.set_frames([Frame(0, 'foo', 'a.c', 9), Frame(1, 'bar', 'b.c', 5)])
        model.set_variables(0, [{'name': 'n', 'value': '2'}])
        self.assertTrue(model.active_watches(0)[0].changed)
        self.assertEqual(list(model.active_watches(0)[0].numeric), [1., 2.])

    def test_reentry_different_scope_generation(self):
        model = ScopeModel()
        model.begin_stop()
        model.set_frames([Frame(0, 'foo', 'a.c', 8)])
        model.set_variables(0, [{'name': 'n', 'value': '1'}])
        model.begin_stop()
        model.set_frames([Frame(0, 'bar', 'b.c', 10)])
        model.begin_stop()
        model.set_frames([Frame(0, 'foo', 'a.c', 8)])
        model.set_variables(0, [{'name': 'n', 'value': '10'}])
        self.assertEqual(len(model.active_watches()), 1)
        self.assertIsNone(model.active_watches()[0].previous)
        self.assertEqual(len(model.watches), 2)

    def test_recursion_separate_frames(self):
        model = ScopeModel()
        model.begin_stop()
        model.set_frames([Frame(0, 'foo', 'a.c', 12), Frame(1, 'foo', 'a.c', 14)])
        model.set_variables(0, [{'name': 'n', 'value': '2'}])
        model.set_variables(1, [{'name': 'n', 'value': '1'}])
        self.assertNotEqual(model.active_watches(0)[0].generation, model.active_watches(1)[0].generation)

    def test_shadowed_lexical_variables(self):
        model = ScopeModel()
        model.begin_stop()
        model.set_frames([Frame(0, 'foo', 'foo.c', 10)])
        model.set_variables(0, [
            {'name': 'n', 'value': '2', 'fullname': 'foo.c', 'line': '3'},
            {'name': 'n', 'value': '9', 'fullname': 'foo.c', 'line': '7', 'shadowed': 'true'}
        ])
        self.assertEqual(len(model.active_watches()), 2)
        self.assertEqual({w.value for w in model.active_watches()}, {'2', '9'})
