import unittest

from _vscode_pyprof.collector.store.task_table import TaskObservation, TaskRecord, TaskState, TaskTable


class TaskTestCase(unittest.TestCase):
    @staticmethod
    def observation(
        task_id: int = 7, state: TaskState = TaskState.WAITING, stack: int = 3, parent: int | None = None
    ) -> TaskObservation:
        return TaskObservation(task_id=task_id, name="worker", parent=parent, thread=1, stack=stack, state=state)


class TestTaskRecord(TaskTestCase):
    def test_first_seen_starts_at_observation_time(self) -> None:
        record = TaskRecord.first_seen(10.0, self.observation())

        self.assertEqual((record.start, record.end, record.state), (10.0, None, TaskState.WAITING))

    def test_matches_with_same_state_stack_and_parent_returns_true(self) -> None:
        record = TaskRecord.first_seen(10.0, self.observation())

        self.assertTrue(record.matches(self.observation()))

    def test_matches_with_other_stack_returns_false(self) -> None:
        record = TaskRecord.first_seen(10.0, self.observation())

        self.assertFalse(record.matches(self.observation(stack=4)))

    def test_observed_returns_record_with_new_state_and_same_start(self) -> None:
        record = TaskRecord.first_seen(10.0, self.observation())

        changed = record.observed(self.observation(state=TaskState.RUNNING, stack=4, parent=2))

        self.assertEqual((changed.state, changed.stack, changed.parent, changed.start), (TaskState.RUNNING, 4, 2, 10.0))

    def test_finished_returns_done_record_with_end_time(self) -> None:
        record = TaskRecord.first_seen(10.0, self.observation())

        self.assertEqual((record.finished(25.0).state, record.finished(25.0).end), (TaskState.DONE, 25.0))

    def test_to_wire_uses_model_field_names(self) -> None:
        record = TaskRecord(
            task_id=5, name="worker", parent=None, thread=1, start=10.0, stack=3, state=TaskState.WAITING
        )

        self.assertDictEqual(
            record.to_profile(),
            {
                "id": 5,
                "name": "worker",
                "parent": None,
                "thread": 1,
                "start": 10.0,
                "end": None,
                "stack": 3,
                "state": "waiting",
            },
        )


class TestTaskTable(TaskTestCase):
    def setUp(self) -> None:
        self.table = TaskTable()

    def test_len_before_any_task_is_zero(self) -> None:
        self.assertEqual(len(self.table), 0)

    def test_reconcile_with_new_task_records_it_and_its_first_state(self) -> None:
        self.table.reconcile(10.0, [self.observation()])

        self.assertEqual([record.task_id for record in self.table.records(new_only=False)], [7])
        self.assertEqual(self.table.events.rows(new_only=False), [[10.0, 7, "waiting"]])

    def test_reconcile_with_state_change_records_event(self) -> None:
        self.table.reconcile(10.0, [self.observation()])

        self.table.reconcile(11.0, [self.observation(state=TaskState.RUNNING)])

        self.assertEqual(self.table.events.rows(new_only=False), [[10.0, 7, "waiting"], [11.0, 7, "running"]])

    def test_reconcile_with_only_stack_change_updates_task_without_event(self) -> None:
        self.table.reconcile(10.0, [self.observation()])

        self.table.reconcile(11.0, [self.observation(stack=9)])

        self.assertEqual(self.table.records(new_only=False)[0].stack, 9)
        self.assertEqual(len(self.table.events), 1)

    def test_reconcile_when_task_is_no_longer_alive_marks_it_done(self) -> None:
        self.table.reconcile(10.0, [self.observation()])

        self.table.reconcile(25.0, [])

        record = self.table.records(new_only=False)[0]
        self.assertEqual((record.state, record.end), (TaskState.DONE, 25.0))
        self.assertEqual(self.table.events.rows(new_only=False)[-1], [25.0, 7, "done"])

    def test_reconcile_with_finished_task_does_not_finish_it_again(self) -> None:
        self.table.reconcile(10.0, [self.observation()])
        self.table.reconcile(25.0, [])

        self.table.reconcile(30.0, [])

        self.assertEqual(self.table.records(new_only=False)[0].end, 25.0)

    def test_records_with_new_only_returns_each_change_once(self) -> None:
        self.table.reconcile(10.0, [self.observation()])

        first = self.table.records(new_only=True)
        second = self.table.records(new_only=True)

        self.assertEqual((len(first), second), (1, []))

    def test_records_with_new_only_skips_unchanged_tasks(self) -> None:
        self.table.reconcile(10.0, [self.observation(task_id=1), self.observation(task_id=2)])
        self.table.records(new_only=True)

        self.table.reconcile(11.0, [self.observation(task_id=1), self.observation(task_id=2, stack=8)])

        self.assertEqual([record.task_id for record in self.table.records(new_only=True)], [2])


if __name__ == "__main__":
    unittest.main()
