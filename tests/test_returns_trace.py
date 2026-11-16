"""Return-edge history and JSONL evidence durability tests."""
from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dbg3k.calltree import ReturnLedger, ReturnObservation
from dbg3k.model import Frame
from dbg3k.trace import SCHEMA, TraceWriter, trace_filename


class ReturnLedgerTests(unittest.TestCase):
    def test_repeated_returns_replace_row_and_keep_ten_recent(self):
        ledger = ReturnLedger()
        for index in range(1, 14):
            item = ReturnObservation("foo", f"bar({index})", str(index * 3), index)
            series = ledger.observe(item, thread="1", callee_function="bar")
        self.assertEqual(len(ledger.series), 1)
        self.assertEqual(series.count, 13)
        self.assertIn("bar(13)", series.label)
        self.assertIn("39", series.label)
        self.assertIn("13×", series.label)
        self.assertIn("stop 13:", series.tooltip)
        self.assertNotIn("stop 3:", series.tooltip)
        self.assertEqual(series.tooltip.count("stop "), 10)
        self.assertEqual(ledger.for_caller(thread="1", caller="foo"), [series])
        self.assertEqual(ledger.for_caller(thread="2", caller="foo"), [])

    def test_caller_edges_are_distinct(self):
        ledger = ReturnLedger()
        for caller in ("foo", "main"):
            ledger.observe(ReturnObservation(caller, "bar(2)", "4", 1),
                           thread="1", callee_function="bar")
        self.assertEqual(len(ledger.series), 2)


class TraceTests(unittest.TestCase):
    def test_filename_exact_and_safe(self):
        d = datetime(2026, 11, 15, 21, 0, tzinfo=timezone.utc)
        self.assertEqual(trace_filename("/tmp/c-main-arm/demo.elf", d),
                         "demo_2026-11-15.jsonl")
        self.assertEqual(trace_filename("/tmp/weird target?.elf", d),
                         "weird_target_2026-11-15.jsonl")

    def test_returns_copy_all_events_from_this_session_only(self):
        with TemporaryDirectory() as folder:
            d = datetime(2026, 11, 15, 21, tzinfo=timezone.utc)
            first = TraceWriter("/tmp/demo.elf", "localhost:1234", folder,
                                now=d, session="first")
            for i in range(1, 23):
                first.record("return", stop=i, thread="1", caller="foo", callee="bar",
                             callee_display=f"bar({i})", value=str(i * 2),
                             origin="gdb-mi-function-finished")
            other = TraceWriter("/tmp/demo.elf", "localhost:1234", folder,
                                now=d, session="other")
            other.record("return", stop=1, thread="1", caller="foo", callee="bar",
                         callee_display="bar(999)", value="999",
                         origin="gdb-mi-function-finished")
            other.close()
            text = first.returns_tsv(thread="1", caller="foo", callee="bar")
            self.assertEqual(len(text.splitlines()), 23)
            self.assertIn("bar(22)", text)
            self.assertNotIn("bar(999)", text)
            first.close()
            path = Path(folder) / "demo_2026-11-15.jsonl"
            records = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(len(records), 27)  # two starts, 23 returns, two ends
            self.assertTrue(all(row["schema"] == SCHEMA for row in records))
            self.assertEqual({row["session"] for row in records}, {"first", "other"})
            self.assertEqual(records[-1]["kind"], "session_end")

    def test_file_survives_unexpected_partial_line(self):
        with TemporaryDirectory() as folder:
            d = datetime(2026, 11, 15, tzinfo=timezone.utc)
            writer = TraceWriter("demo.elf", "localhost:1234", folder, now=d)
            writer.record("return", stop=1, thread="1", caller="foo", callee="bar",
                          callee_display="bar(1)", value="3", origin="gdb-mi-function-finished")
            with writer.path.open("a", encoding="utf-8") as out:
                out.write('{"not_closed": ')
            result = writer.returns_tsv(thread="1", caller="foo", callee="bar")
            self.assertIn("bar(1)", result)
            writer.close()


    def test_new_session_resynchronizes_after_crash_fragment(self):
        with TemporaryDirectory() as folder:
            d = datetime(2026, 11, 15, 21, tzinfo=timezone.utc)
            path = Path(folder) / "demo_2026-11-15.jsonl"
            path.write_text('{"broken":', encoding="utf-8")
            writer = TraceWriter("demo.elf", "localhost:1234", folder,
                                 now=d, session="recovered")
            writer.record("return", stop=1, thread="1", caller="foo",
                          callee="bar", callee_display="bar(4)", value="12",
                          origin="gdb-mi-function-finished")
            writer.close()
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 4)  # partial + session start + return + end
            self.assertEqual(json.loads(lines[1])["kind"], "session_start")
            self.assertEqual(json.loads(lines[2])["kind"], "return")


if __name__ == "__main__":
    unittest.main()
