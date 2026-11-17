"""Wiring checks test declared dependencies, not task control flow."""
from contextlib import redirect_stderr, redirect_stdout
import copy
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dbg3k.kodama_wiring import expression, import_board, main, yaml_text


def fixture():
    items = [dict(id=name, type='shape', content=label) for name, label in (
        ('init', '<p>Task::init()</p>'),
        ('producer', '<p>Task::produce()<br>SUPERLOOP</p><p>PEND[ACK]</p>'),
        ('consumer', '<p>Task::consume()</p><p>PEND[AB,C]</p>'),
        ('events', '<p>Kodama::events</p>'), ('levels', '<p>Kodama::levels</p>'))]
    for a, b, label in [('init', 'producer', 'KODAMA::SPAWN'),
                       ('init', 'consumer', 'KODAMA::SPAWN'),
                       ('init', 'levels', 'INIT_COMPLETE'),
                       ('levels', 'producer', 'SUB[INIT_COMPLETE]'),
                       ('levels', 'consumer', 'SUB[INIT_COMPLETE]'),
                       ('producer', 'events', 'event::A'),
                       ('producer', 'events', 'event::B'),
                       ('producer', 'events', 'event::C'),
                       ('consumer', 'events', 'ACK'),
                       ('events', 'producer', 'SUB[ACK]'),
                       ('events', 'consumer', 'SUB[A AND B]'),
                       ('events', 'consumer', 'SUB[C]')]:
        items.append(dict(id=str(len(items)), type='connector', start=dict(item=a), end=dict(item=b),
                          style=dict(startStrokeCap='none', endStrokeCap='rounded_stealth'),
                          captions=[dict(content=f'<p>{label}</p>')]))
    return dict(format='miro-diagram-export/v1', exportedAt='fixture', items=items)


class ExpressionTests(unittest.TestCase):
    def test_boolean_grammar_precedence_and_identifiers(self):
        self.assertEqual(expression(' A and B OR C '), ('A AND B OR C', {'A', 'B', 'C'}))
        self.assertEqual(expression('A AND (B OR C)'), ('A AND (B OR C)', {'A', 'B', 'C'}))
        self.assertEqual(expression('(AB)'), ('AB', {'AB'}))  # Never split identifiers into letters.
        self.assertEqual(expression('b AND c', {'b': 'B', 'c': 'C'}), ('B AND C', {'B', 'C'}))
        self.assertEqual(expression('READY_1'), ('READY_1', {'READY_1'}))

    def test_reject_ambiguous_or_unsupported_syntax_and_limits(self):
        for text in ('', 'A B', 'A,B', 'A && B', 'A OR', 'AND A', 'NOT A', 'A XOR B',
                     '(A', 'A)', 'A & B', 'A; print(1)', 'A' * 65,
                     '(' * 34 + 'A' + ')' * 34, ' OR '.join(['A'] * 130)):
            with self.subTest(text=text), self.assertRaises(ValueError):
                expression(text)


class WiringTests(unittest.TestCase):
    def test_complete_wiring_preserves_separate_sensitivities_and_no_behavior(self):
        model = import_board(fixture())
        self.assertEqual(model['tasks']['init']['spawns'], ['consume', 'produce'])
        self.assertEqual(model['occurrences'], ['A', 'ACK', 'B', 'C'])
        self.assertEqual(model['levels'], ['INIT_COMPLETE'])
        conditions = model['tasks']['consume']['sensitivities']
        self.assertEqual([(c['kind'], c['expression']) for c in conditions],
                         [('level', 'INIT_COMPLETE'), ('occurrence', 'A AND B'), ('occurrence', 'C')])
        text = yaml_text(model)
        self.assertNotIn('PEND', text)
        self.assertNotIn('SUPERLOOP', text)
        self.assertNotIn('startup', text)
        self.assertIn('expression: "A AND B"', text)

    def test_all_or_branches_require_producers_and_unused_publications_fail(self):
        board = fixture()
        board['items'][-1]['captions'][0]['content'] = 'SUB[C OR MISSING]'
        board['items'][10]['captions'][0]['content'] = 'UNUSED'
        with self.assertRaises(ValueError) as caught:
            import_board(board)
        message = str(caught.exception)
        self.assertIn('MISSING: consumed by consume, but has no producer', message)
        self.assertIn('A: consumed by consume, but has no producer', message)
        self.assertIn('UNUSED: produced by produce, but has no consumer', message)

    def test_case_aliases_explicit_and_legacy_and_caption(self):
        board = fixture()
        board['items'][11]['captions'][0]['content'] = 'event::b'
        board['items'][-2]['captions'][0]['content'] = 'subAND[A,B]'
        with self.assertRaisesRegex(ValueError, 'occurrence B: consumed'):
            import_board(board)
        self.assertEqual(import_board(board, {'b': 'B'})['occurrences'], ['A', 'ACK', 'B', 'C'])
        with self.assertRaisesRegex(ValueError, 'Aliases must map directly'):
            import_board(board, {'b': 'B', 'B': 'C'})

    def test_namespaces_do_not_satisfy_each_other(self):
        board = fixture()
        # Reuse the level name as an occurrence: its level producer cannot satisfy it.
        board['items'][-1]['captions'][0]['content'] = 'SUB[INIT_COMPLETE]'
        with self.assertRaisesRegex(ValueError, 'occurrence INIT_COMPLETE: consumed'):
            import_board(board)

    def test_external_producers_and_reverse_arrows_are_explicit(self):
        board = fixture()
        board['items'][0]['content'] = 'External::input'
        # External actors do not spawn tasks: drop those two relations.
        board['items'] = [i for i in board['items'] if i['id'] not in ('5', '6')]
        edge = board['items'][-1]
        edge['start'], edge['end'] = edge['end'], edge['start']
        edge['style'] = dict(startStrokeCap='rounded_stealth', endStrokeCap='none')
        model = import_board(board)
        self.assertEqual(model['externals']['input']['updates_levels'], ['INIT_COMPLETE'])

    def test_reject_missing_endpoints_duplicates_unsupported_relations_and_unlabeled_edges(self):
        for change in ('dangling', 'duplicate_id', 'duplicate_edge', 'unknown_shape', 'unlabeled', 'two_arrows'):
            board = fixture()
            if change == 'dangling':
                board['items'][-1]['end']['item'] = 'absent'
            elif change == 'duplicate_id':
                board['items'].append(copy.deepcopy(board['items'][0]))
            elif change == 'duplicate_edge':
                duplicate = copy.deepcopy(board['items'][-1]); duplicate['id'] = 'extra'
                board['items'].append(duplicate)
            elif change == 'unknown_shape':
                board['items'][0]['content'] = 'guess what this means'
            elif change == 'unlabeled':
                board['items'][-1]['captions'] = []
            else:
                board['items'][-1]['style']['startStrokeCap'] = 'rounded_stealth'
            with self.subTest(change=change), self.assertRaises(ValueError):
                import_board(board)

    def test_malformed_connector_shapes_are_reported_as_validation_errors(self):
        for field, value in [('start', None), ('end', {'item': []}), ('style', []),
                             ('captions', None), ('captions', [None])]:
            board = fixture()
            board['items'][-1][field] = value
            with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, 'Connector '):
                import_board(board)

    def test_yaml_implicit_boolean_and_null_keys_are_quoted(self):
        text = yaml_text({'true': {'on': ['A AND B', 'line\nbreak']}, 'null': {}, 'off': []})
        self.assertIn('"true":', text)
        self.assertIn('"on":', text)
        self.assertIn('"null": {}', text)
        self.assertIn('"off": []', text)
        self.assertIn('"line\\nbreak"', text)

    def test_cli_validates_before_writing_and_never_overwrites(self):
        with TemporaryDirectory() as folder:
            source, output = Path(folder) / 'board.json', Path(folder) / 'wiring.yaml'
            board = fixture()
            source.write_text(json.dumps(board))
            with redirect_stderr(io.StringIO()):
                self.assertEqual(main([str(source), '--output', str(output)]), 0)
                original = output.read_bytes()
                self.assertEqual(main([str(source), '--output', str(output)]), 1)
                self.assertEqual(output.read_bytes(), original)
                board['items'][-1]['captions'][0]['content'] = 'SUB[UNKNOWN]'
                source.write_text(json.dumps(board))
                other = Path(folder) / 'invalid.yaml'
                self.assertEqual(main([str(source), '--output', str(other)]), 1)
                self.assertFalse(other.exists())
                with redirect_stdout(io.StringIO()) as stdout:
                    self.assertEqual(main([str(source)]), 1)
                    self.assertEqual(stdout.getvalue(), '')


if __name__ == '__main__':
    unittest.main()
