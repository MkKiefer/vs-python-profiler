import unittest

from _vspyprof.collector.store.task_table import TaskObservation, TaskRecord, TaskState, TaskTable


class TaskTestCase(unittest.TestCase):
    @staticmethod
    def observation(
        address: int = 7,
        state: TaskState = TaskState.WAITING,
        stack: int = 3,
        parent_address: int | None = None,
        name: str = "worker",
    ) -> TaskObservation:
        return TaskObservation(
            address=address, name=name, parent_address=parent_address, thread=1, stack=stack, state=state
        )


class TestTaskRecord(TaskTestCase):
    def test_first_seen_starts_at_observation_time(self) -> None:
        record = TaskRecord.first_seen(1, 10.0, self.observation(), parent=None)

        self.assertEqual((record.task_id, record.start, record.end, record.state), (1, 10.0, None, TaskState.WAITING))

    def test_matches_with_same_state_stack_and_parent_returns_true(self) -> None:
        record = TaskRecord.first_seen(1, 10.0, self.observation(), parent=None)

        self.assertTrue(record.matches(self.observation(), parent=None))

    def test_matches_with_other_stack_returns_false(self) -> None:
        record = TaskRecord.first_seen(1, 10.0, self.observation(), parent=None)

        self.assertFalse(record.matches(self.observation(stack=4), parent=None))

    def test_matches_with_other_parent_returns_false(self) -> None:
        record = TaskRecord.first_seen(1, 10.0, self.observation(), parent=None)

        self.assertFalse(record.matches(self.observation(), parent=2))

    def test_observed_returns_record_with_new_state_and_same_start(self) -> None:
        record = TaskRecord.first_seen(1, 10.0, self.observation(), parent=None)

        changed = record.observed(self.observation(state=TaskState.RUNNING, stack=4), parent=2)

        self.assertEqual((changed.state, changed.stack, changed.parent, changed.start), (TaskState.RUNNING, 4, 2, 10.0))

    def test_finished_returns_done_record_with_end_time(self) -> None:
        record = TaskRecord.first_seen(1, 10.0, self.observation(), parent=None)

        self.assertEqual((record.finished(25.0).state, record.finished(25.0).end), (TaskState.DONE, 25.0))

    def test_to_profile_uses_model_field_names(self) -> None:
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

    def records(self) -> list[TaskRecord]:
        return self.table.records(new_only=False)

    def test_len_before_any_task_is_zero(self) -> None:
        self.assertEqual(len(self.table), 0)

    def test_reconcile_with_new_task_records_it_and_its_first_state(self) -> None:
        self.table.reconcile(10.0, [self.observation()])

        self.assertEqual([record.task_id for record in self.records()], [1])
        self.assertEqual(self.table.events.rows(new_only=False), [[10.0, 1, "waiting"]])

    def test_reconcile_with_new_tasks_in_one_tick_gives_each_its_own_id(self) -> None:
        self.table.reconcile(10.0, [self.observation(address=7), self.observation(address=8)])

        self.assertEqual(sorted(record.task_id for record in self.records()), [1, 2])

    def test_reconcile_with_state_change_records_event(self) -> None:
        self.table.reconcile(10.0, [self.observation()])

        self.table.reconcile(11.0, [self.observation(state=TaskState.RUNNING)])

        self.assertEqual(self.table.events.rows(new_only=False), [[10.0, 1, "waiting"], [11.0, 1, "running"]])

    def test_reconcile_with_only_stack_change_updates_task_without_event(self) -> None:
        self.table.reconcile(10.0, [self.observation()])

        self.table.reconcile(11.0, [self.observation(stack=9)])

        self.assertEqual(self.records()[0].stack, 9)
        self.assertEqual(len(self.table.events), 1)

    def test_reconcile_when_task_is_no_longer_alive_marks_it_done(self) -> None:
        self.table.reconcile(10.0, [self.observation()])

        self.table.reconcile(25.0, [])

        record = self.records()[0]
        self.assertEqual((record.state, record.end), (TaskState.DONE, 25.0))
        self.assertEqual(self.table.events.rows(new_only=False)[-1], [25.0, 1, "done"])

    def test_reconcile_with_finished_task_does_not_finish_it_again(self) -> None:
        self.table.reconcile(10.0, [self.observation()])
        self.table.reconcile(25.0, [])

        self.table.reconcile(30.0, [])

        self.assertEqual(self.records()[0].end, 25.0)
        self.assertEqual(len(self.table.events), 2)

    def test_reconcile_with_address_of_finished_task_records_new_task(self) -> None:
        self.table.reconcile(10.0, [self.observation()])
        self.table.reconcile(25.0, [])

        self.table.reconcile(30.0, [self.observation()])
        self.table.reconcile(40.0, [])

        old, new = self.records()
        self.assertEqual((old.start, old.end), (10.0, 25.0))
        self.assertEqual((new.task_id, new.start, new.end, new.state), (2, 30.0, 40.0, TaskState.DONE))

    def test_reconcile_with_other_name_at_same_address_finishes_old_task_and_starts_new_one(self) -> None:
        self.table.reconcile(10.0, [self.observation(name="Task-1")])

        self.table.reconcile(11.0, [self.observation(name="Task-2")])

        old, new = self.records()
        self.assertEqual((old.name, old.end), ("Task-1", 11.0))
        self.assertEqual((new.name, new.start, new.end), ("Task-2", 11.0, None))

    def test_reconcile_with_parent_seen_later_in_same_tick_records_parent_task_id(self) -> None:
        child = self.observation(address=9, parent_address=3, name="child")
        parent = self.observation(address=3, name="parent")

        self.table.reconcile(10.0, [child, parent])

        records = {record.name: record for record in self.records()}
        self.assertEqual(records["child"].parent, records["parent"].task_id)
        self.assertIsNone(records["parent"].parent)

    def test_reconcile_with_unknown_parent_address_records_no_parent(self) -> None:
        self.table.reconcile(10.0, [self.observation(parent_address=3)])

        self.assertIsNone(self.records()[0].parent)

    def test_reconcile_after_many_finished_tasks_only_reports_live_changes(self) -> None:
        self.table.reconcile(10.0, [self.observation(address=address) for address in range(1000)])
        self.table.reconcile(11.0, [])
        self.table.records(new_only=True)

        self.table.reconcile(12.0, [self.observation(address=5000)])

        self.assertEqual([record.start for record in self.table.records(new_only=True)], [12.0])

    def test_records_with_new_only_returns_each_change_once(self) -> None:
        self.table.reconcile(10.0, [self.observation()])

        first = self.table.records(new_only=True)
        second = self.table.records(new_only=True)

        self.assertEqual((len(first), second), (1, []))

    def test_records_with_new_only_skips_unchanged_tasks(self) -> None:
        self.table.reconcile(10.0, [self.observation(address=1), self.observation(address=2)])
        self.table.records(new_only=True)

        self.table.reconcile(11.0, [self.observation(address=1), self.observation(address=2, stack=8)])

        self.assertEqual([record.task_id for record in self.table.records(new_only=True)], [2])


if __name__ == "__main__":
    unittest.main()
