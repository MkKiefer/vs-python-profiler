import random
import unittest
from collections import Counter

from _vspyprof.collector.store.column_snapshot import ColumnSnapshot
from _vspyprof.collector.store.sample_runs import Sample, SampleRuns
from _vspyprof.wire import JsonObject

type Row = tuple[int, int, int, int, int]
"""(tick, count, thread index, stack, status)"""


class TestSampleRuns(unittest.TestCase):
    def setUp(self) -> None:
        self.runs = SampleRuns()

    def rows(self, profile: JsonObject) -> list[Row]:
        columns = [profile[name] for name in ("tick", "count", "thread", "stack", "status")]
        assert all(isinstance(column, list) for column in columns)
        return [tuple(row) for row in zip(*columns, strict=True)]

    def all_rows(self) -> list[Row]:
        return self.rows(self.runs.to_profile(new_only=False))

    def test_equal_samples_in_consecutive_ticks_form_one_run(self) -> None:
        for t in (1.0, 2.0, 3.0):
            self.runs.add_tick(t, [Sample(101, 7, 3)])

        profile = self.runs.to_profile(new_only=False)

        self.assertEqual(self.rows(profile), [(0, 3, 0, 7, 3)])
        self.assertEqual((profile["ticks"], profile["threadIds"]), ([1.0, 2.0, 3.0], [101]))

    def test_changed_stack_or_status_starts_a_new_run(self) -> None:
        self.runs.add_tick(1.0, [Sample(101, 7, 3)])
        self.runs.add_tick(2.0, [Sample(101, 8, 3)])
        self.runs.add_tick(3.0, [Sample(101, 8, 0)])

        self.assertEqual(self.all_rows(), [(0, 1, 0, 7, 3), (1, 1, 0, 8, 3), (2, 1, 0, 8, 0)])

    def test_thread_missing_from_a_tick_ends_its_run(self) -> None:
        self.runs.add_tick(1.0, [Sample(101, 7, 3)])
        self.runs.add_tick(2.0, [])
        self.runs.add_tick(3.0, [Sample(101, 7, 3)])

        self.assertEqual(self.all_rows(), [(0, 1, 0, 7, 3), (2, 1, 0, 7, 3)])

    def test_run_longer_than_max_is_split(self) -> None:
        for tick in range(SampleRuns.MAX_RUN + 5):
            self.runs.add_tick(float(tick), [Sample(101, 7, 3)])

        self.assertEqual(self.all_rows(), [(0, SampleRuns.MAX_RUN, 0, 7, 3), (SampleRuns.MAX_RUN, 5, 0, 7, 3)])

    def test_threads_get_indexes_in_order_of_appearance(self) -> None:
        self.runs.add_tick(1.0, [Sample(0x7F00_0000_0002, 7, 0), Sample(0x7F00_0000_0001, 7, 0)])

        profile = self.runs.to_profile(new_only=False)

        self.assertEqual(profile["threadIds"], [0x7F00_0000_0002, 0x7F00_0000_0001])
        self.assertEqual(sorted(row[2] for row in self.rows(profile)), [0, 1])

    def test_same_sample_twice_in_one_tick_is_kept_twice(self) -> None:
        self.runs.add_tick(1.0, [Sample(101, 7, 0), Sample(101, 7, 0)])

        self.assertEqual(sum(row[1] for row in self.all_rows()), 2)

    def test_status_keeps_the_bits_the_dashboard_reads(self) -> None:
        self.runs.add_tick(1.0, [Sample(101, 7, 0x103)])

        self.assertEqual(self.all_rows()[0][4], 0x03)

    def test_new_only_hands_out_rows_and_ticks_once_and_closes_open_runs(self) -> None:
        self.runs.add_tick(1.0, [Sample(101, 7, 3)])
        first = self.runs.to_profile(new_only=True)
        self.runs.add_tick(2.0, [Sample(101, 7, 3)])

        second = self.runs.to_profile(new_only=True)

        self.assertEqual((self.rows(first), first["ticks"], first["threadIds"]), ([(0, 1, 0, 7, 3)], [1.0], [101]))
        self.assertEqual((self.rows(second), second["ticks"], second["threadIds"]), ([(1, 1, 0, 7, 3)], [2.0], []))

    def test_snapshot_streams_the_rows_written_when_taken(self) -> None:
        self.runs.add_tick(1.0, [Sample(101, 7, 3)])
        snapshot = self.runs.snapshot()
        self.runs.add_tick(2.0, [Sample(102, 8, 3)])
        self.runs.flush()

        count, ticks = snapshot["count"], snapshot["ticks"]
        assert isinstance(count, ColumnSnapshot) and isinstance(ticks, ColumnSnapshot)
        self.assertEqual(
            (list(count.chunks(10)), list(ticks.chunks(10)), snapshot["threadIds"]), ([[1]], [[1.0]], [101])
        )

    def test_random_samples_expand_back_exactly_with_rows_ordered_by_last_tick(self) -> None:
        generator = random.Random(1234)
        taken: Counter[tuple[int, int, int, int]] = Counter()
        rows: list[Row] = []
        current = [Sample(100 + thread, 1, 3) for thread in range(4)]
        for tick in range(3000):
            for thread in range(4):  # like real threads, mostly keep doing what they did
                if generator.random() < 0.05:
                    current[thread] = Sample(100 + thread, generator.choice((1, 2, 3)), generator.choice((0, 3)))
            samples = [sample for sample in current if generator.random() > 0.02]
            if generator.random() < 0.01 and samples:
                samples.append(samples[0])  # a repeated sample
            self.runs.add_tick(float(tick), samples)
            taken.update((tick, sample.thread_id, sample.stack, sample.status) for sample in samples)
            if generator.random() < 0.02:  # a live delta closes the open runs
                rows += self.rows(self.runs.to_profile(new_only=True))
        rows += self.rows(self.runs.to_profile(new_only=True))
        thread_ids = self.runs.to_profile(new_only=False)["threadIds"]
        assert isinstance(thread_ids, list)

        expanded = Counter(
            (tick + offset, thread_ids[thread], stack, status)
            for tick, count, thread, stack, status in rows
            for offset in range(count)
        )
        last_ticks = [tick + count - 1 for tick, count, _, _, _ in rows]

        self.assertEqual(expanded, taken)
        self.assertEqual(last_ticks, sorted(last_ticks))
        self.assertTrue(all(1 <= row[1] <= SampleRuns.MAX_RUN for row in rows))
        self.assertLess(len(rows), sum(taken.values()) / 2)  # mostly-equal samples compress


if __name__ == "__main__":
    unittest.main()
