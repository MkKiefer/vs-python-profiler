import os
import unittest
from _remote_debugging import AwaitedInfo, CoroInfo, FrameInfo, InterpreterInfo, LocationInfo, TaskInfo, ThreadInfo

from _vscode_pyprof.frame_classifier import FrameCategory, FrameClassifier
from _vscode_pyprof.records import AllocationSite, MemorySnapshot
from _vscode_pyprof.store import Store
from _vscode_pyprof.wire import WireReader

ROOT = os.path.abspath(os.sep)
INTERNAL_DIR = os.path.join(ROOT, "ext", "_vscode_pyprof")
APP = os.path.join(ROOT, "work", "app.py")
LAUNCHER = os.path.join(INTERNAL_DIR, "launcher.py")
AGENT = os.path.join(INTERNAL_DIR, "agent.py")


class StoreTestCase(unittest.TestCase):
    def setUp(self) -> None:
        classifier = FrameClassifier([os.path.join(ROOT, "py", "lib")], [], INTERNAL_DIR)
        self.store = Store(classifier)

    @staticmethod
    def frame(filename: str, funcname: str, line: int) -> FrameInfo:
        return FrameInfo((filename, LocationInfo((line, line, 0, 0)), funcname, None))

    @staticmethod
    def threads(*stacks: tuple[int, int, list[FrameInfo]]) -> list[InterpreterInfo]:
        return [InterpreterInfo((0, [ThreadInfo(stack) for stack in stacks]))]

    def function_names(self, wire: WireReader, stack: int) -> list[str]:
        """Function names of a stack, root first."""
        frames = wire.get_list("frames")
        stacks = wire.get_list("stacks")
        names: list[str] = []
        while stack >= 0:
            entry = stacks[stack]
            assert isinstance(entry, list)
            stack, frame_id = entry
            frame = frames[frame_id]
            assert isinstance(frame, list)
            names.append(str(frame[1]))
        return names[::-1]


class TestStoreInterning(StoreTestCase):
    def test_intern_path_with_same_frames_returns_same_stack(self) -> None:
        path = [(APP, "main", 1), (APP, "work", 5)]

        first = self.store.intern_path(path)
        second = self.store.intern_path(path)

        self.assertEqual(first, second)

    def test_intern_path_with_shared_prefix_reuses_parent_stack(self) -> None:
        self.store.intern_path([(APP, "main", 1), (APP, "a", 5)])
        self.store.intern_path([(APP, "main", 1), (APP, "b", 9)])

        delta = WireReader(self.store.delta())

        self.assertEqual(len(delta.get_list("frames")), 3)
        self.assertEqual(delta.get_list("stacks"), [[-1, 0], [0, 1], [0, 2]])

    def test_intern_path_with_empty_path_returns_no_stack(self) -> None:
        self.assertEqual(self.store.intern_path([]), Store.NO_STACK)

    def test_intern_path_records_frame_category(self) -> None:
        self.store.intern_path([(APP, "main", 1), ("<native>", "<native>", 0)])

        frames = WireReader(self.store.delta()).get_list("frames")

        self.assertEqual(
            frames,
            [[APP, "main", 1, int(FrameCategory.USER)], ["<native>", "<native>", 0, int(FrameCategory.SYNTHETIC)]],
        )

    def test_intern_traceback_with_strip_launcher_drops_bootstrap_frames(self) -> None:
        self.store.configure(strip_launcher=True)

        stack = self.store.intern_traceback([("<string>", "<module>", 1), (LAUNCHER, "run", 9), (APP, "main", 1)])

        self.assertListEqual(self.function_names(WireReader(self.store.delta()), stack), ["main"])

    def test_intern_traceback_without_strip_launcher_keeps_all_frames(self) -> None:
        stack = self.store.intern_traceback([("<string>", "<module>", 1), (APP, "main", 1)])

        self.assertListEqual(self.function_names(WireReader(self.store.delta()), stack), ["<module>", "main"])

    def test_intern_traceback_with_only_launcher_frames_returns_no_stack(self) -> None:
        self.store.configure(strip_launcher=True)

        stack = self.store.intern_traceback([("<string>", "<module>", 1), (LAUNCHER, "run", 9)])

        self.assertEqual(stack, Store.NO_STACK)


class TestStoreSamples(StoreTestCase):
    def test_add_thread_sample_records_one_row_per_thread(self) -> None:
        main_stack = [self.frame(APP, "work", 5), self.frame(APP, "main", 1)]  # leaf first
        worker_stack = [self.frame(APP, "loop", 20)]

        self.store.add_thread_sample(12.3456, self.threads((101, 3, main_stack), (102, 0, worker_stack)))

        samples = WireReader(self.store.delta()).get_object("samples")
        self.assertEqual(samples.get_list("t"), [12.346, 12.346])
        self.assertEqual(samples.get_list("tid"), [101, 102])
        self.assertEqual(samples.get_list("status"), [3, 0])

    def test_add_thread_sample_stores_stack_root_first(self) -> None:
        self.store.add_thread_sample(
            1.0, self.threads((1, 0, [self.frame(APP, "work", 5), self.frame(APP, "main", 1)]))
        )

        delta = WireReader(self.store.delta())
        stack = delta.get_object("samples").get_list("stack")[0]

        assert isinstance(stack, int)
        self.assertListEqual(self.function_names(delta, stack), ["main", "work"])

    def test_add_thread_sample_skips_profiler_threads(self) -> None:
        agent_stack = [self.frame(AGENT, "run", 3)]

        self.store.add_thread_sample(1.0, self.threads((1, 0, agent_stack)))

        self.assertEqual(WireReader(self.store.delta()).get_object("samples").get_list("t"), [])

    def test_add_thread_sample_skips_threads_without_frames(self) -> None:
        self.store.add_thread_sample(1.0, self.threads((1, 0, [])))

        self.assertEqual(WireReader(self.store.delta()).get_object("samples").get_list("t"), [])

    def test_add_thread_sample_with_strip_launcher_removes_bootstrap_frames(self) -> None:
        self.store.configure(strip_launcher=True)
        stack = [self.frame(APP, "main", 1), self.frame(LAUNCHER, "run", 9), self.frame("<string>", "<module>", 1)]

        self.store.add_thread_sample(1.0, self.threads((1, 0, stack)))

        delta = WireReader(self.store.delta())
        stack_id = delta.get_object("samples").get_list("stack")[0]
        assert isinstance(stack_id, int)
        self.assertListEqual(self.function_names(delta, stack_id), ["main"])

    def test_add_thread_sample_counts_each_tick_once(self) -> None:
        tick = self.threads((1, 0, [self.frame(APP, "a", 1)]), (2, 0, [self.frame(APP, "b", 2)]))

        self.store.add_thread_sample(1.0, tick)
        self.store.add_thread_sample(2.0, tick)

        self.assertEqual(self.store.stats()["samples"], 2)

    def test_add_async_sample_records_rows_in_async_table(self) -> None:
        self.store.add_async_sample(4.0, [([self.frame(APP, "handler", 7)], 55, 1)])

        delta = WireReader(self.store.delta())

        self.assertEqual(delta.get_object("asyncSamples").get_list("tid"), [55])
        self.assertEqual(delta.get_object("samples").get_list("tid"), [])

    def test_record_error_increments_error_count(self) -> None:
        self.store.record_error()

        self.assertEqual(self.store.stats()["errors"], 1)

    def test_set_sampling_rate_is_reported_in_stats(self) -> None:
        self.store.set_sampling_rate(987.5)

        self.assertEqual(self.store.stats()["rateHz"], 987.5)


class TestStoreTasks(StoreTestCase):
    def awaited(self, task_id: int, name: str, awaiter: int | str | None = None) -> list[AwaitedInfo]:
        coroutine = CoroInfo(([self.frame(APP, "worker", 30)], name))
        awaited_by = [CoroInfo(([], awaiter))] if awaiter is not None else []
        return [AwaitedInfo((1, [TaskInfo((task_id, name, [coroutine], awaited_by))]))]

    def test_has_tasks_before_any_update_returns_false(self) -> None:
        self.assertFalse(self.store.has_tasks())

    def test_update_tasks_with_new_task_records_it_as_waiting(self) -> None:
        self.store.update_tasks(10.0, self.awaited(7, "worker-1"), running_ids=set())

        task = WireReader.of(WireReader(self.store.delta()).get_list("tasks")[0])

        self.assertEqual((task.get_int("id"), task.get_str("name"), task.get_str("state")), (7, "worker-1", "waiting"))
        self.assertTrue(self.store.has_tasks())

    def test_update_tasks_with_running_task_records_running_state(self) -> None:
        self.store.update_tasks(10.0, self.awaited(7, "worker-1"), running_ids={7})

        task = WireReader.of(WireReader(self.store.delta()).get_list("tasks")[0])

        self.assertEqual(task.get_str("state"), "running")

    def test_update_tasks_with_awaiter_id_records_parent(self) -> None:
        self.store.update_tasks(10.0, self.awaited(7, "worker-1", awaiter=3), running_ids=set())

        task = WireReader.of(WireReader(self.store.delta()).get_list("tasks")[0])

        self.assertEqual(task.get_int("parent"), 3)

    def test_update_tasks_with_awaiter_name_records_no_parent(self) -> None:
        self.store.update_tasks(10.0, self.awaited(7, "worker-1", awaiter="Task-1"), running_ids=set())

        task = WireReader.of(WireReader(self.store.delta()).get_list("tasks")[0])

        self.assertFalse(task.has("parent"))

    def test_update_tasks_when_task_disappears_marks_it_done(self) -> None:
        self.store.update_tasks(10.0, self.awaited(7, "worker-1"), running_ids=set())

        self.store.update_tasks(25.0, [], running_ids=set())

        delta = WireReader(self.store.delta())
        task = WireReader.of(delta.get_list("tasks")[0])
        self.assertEqual((task.get_str("state"), task.get_float("end")), ("done", 25.0))
        self.assertEqual(delta.get_list("taskEvents"), [[10.0, 7, "waiting"], [25.0, 7, "done"]])

    def test_update_tasks_without_changes_reports_no_dirty_tasks(self) -> None:
        self.store.update_tasks(10.0, self.awaited(7, "worker-1"), running_ids=set())
        self.store.delta()

        self.store.update_tasks(11.0, self.awaited(7, "worker-1"), running_ids=set())

        self.assertEqual(WireReader(self.store.delta()).get_list("tasks"), [])


class TestStoreSeriesAndEvents(StoreTestCase):
    def test_add_track_appends_rounded_point(self) -> None:
        self.store.add_track("rss", 10.004, 2048)

        tracks = WireReader(self.store.delta()).get_object("tracks")

        self.assertEqual(tracks.get_list("rss"), [[10.0, 2048]])

    def test_add_gc_appends_collection(self) -> None:
        self.store.add_gc(5.0, 1.25, 2, 40, 9000)

        self.assertEqual(WireReader(self.store.delta()).get_list("gc"), [[5.0, 1.25, 2, 40, 9000]])

    def test_add_marker_with_explicit_time_uses_it(self) -> None:
        self.store.add_marker("deploy", 42.0)

        self.assertEqual(WireReader(self.store.delta()).get_list("markers"), [[42.0, "deploy"]])

    def test_add_event_merges_extra_fields(self) -> None:
        self.store.add_event("slow-callback", "took 0.2s", 7.0, {"seconds": 0.2})

        events = WireReader(self.store.delta()).get_list("events")

        self.assertEqual(events, [{"seconds": 0.2, "t": 7.0, "kind": "slow-callback", "message": "took 0.2s"}])

    def test_set_thread_name_reports_thread_in_next_delta(self) -> None:
        self.store.set_thread_name(101, "MainThread")

        self.assertEqual(WireReader(self.store.delta()).get_raw("threads"), {"101": "MainThread"})

    def test_set_thread_name_with_unchanged_name_is_not_reported_again(self) -> None:
        self.store.set_thread_name(101, "MainThread")
        self.store.delta()

        self.store.set_thread_name(101, "MainThread")

        self.assertEqual(WireReader(self.store.delta()).get_raw("threads"), {})

    def test_add_object_counts_reports_latest_counts(self) -> None:
        self.store.add_object_counts(3.0, [["dict", 10]])

        self.assertEqual(
            WireReader(self.store.delta()).get_list("objectCounts"), [{"t": 3.0, "counts": [["dict", 10]]}]
        )

    def test_to_session_ms_converts_perf_counter_difference(self) -> None:
        origin = self.store.to_session_ms(0.0)

        self.assertAlmostEqual(self.store.to_session_ms(1.5) - origin, 1500.0)


class TestStoreDeltas(StoreTestCase):
    def snapshot(self) -> MemorySnapshot:
        return MemorySnapshot(
            snapshot_id=1,
            label="A",
            t=1.0,
            total_size=10,
            total_count=1,
            other_size=0,
            other_count=0,
            traced=10,
            peak=10,
            take_ms=None,
            sites=(AllocationSite(0, 10, 1),),
        )

    def test_delta_returns_only_data_added_since_previous_delta(self) -> None:
        self.store.add_track("rss", 1.0, 100)
        self.store.intern_path([(APP, "main", 1)])
        self.store.delta()

        self.store.add_track("rss", 2.0, 200)

        delta = WireReader(self.store.delta())
        self.assertEqual(delta.get_object("tracks").get_list("rss"), [[2.0, 200]])
        self.assertEqual(delta.get_list("frames"), [])

    def test_delta_includes_meta_only_when_changed(self) -> None:
        first = WireReader(self.store.delta())
        second = WireReader(self.store.delta())
        self.store.set_meta(pid=99)
        third = WireReader(self.store.delta())

        self.assertTrue(first.has("meta"))
        self.assertFalse(second.has("meta"))
        self.assertEqual(third.get_object("meta").get_int("pid"), 99)

    def test_delta_reports_new_snapshot_once(self) -> None:
        self.store.add_snapshot(self.snapshot())

        first = WireReader(self.store.delta())
        second = WireReader(self.store.delta())

        self.assertEqual(len(first.get_list("snapshots")), 1)
        self.assertEqual(second.get_list("snapshots"), [])

    def test_full_returns_everything_regardless_of_previous_deltas(self) -> None:
        self.store.add_track("rss", 1.0, 100)
        self.store.set_thread_name(1, "MainThread")
        self.store.add_snapshot(self.snapshot())
        self.store.delta()

        full = WireReader(self.store.full())

        self.assertEqual(full.get_object("tracks").get_list("rss"), [[1.0, 100]])
        self.assertEqual(full.get_raw("threads"), {"1": "MainThread"})
        self.assertEqual(len(full.get_list("snapshots")), 1)

    def test_full_is_tagged_as_pyprof_file(self) -> None:
        full = WireReader(self.store.full())

        self.assertEqual((full.get_str("format"), full.get_int("version")), (Store.FORMAT, Store.FORMAT_VERSION))


if __name__ == "__main__":
    unittest.main()
