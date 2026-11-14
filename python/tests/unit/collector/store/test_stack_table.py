import os
import unittest
from _remote_debugging import FrameInfo, LocationInfo

from _vscode_pyprof.collector.frames.frame_classifier import FrameCategory, FrameClassifier
from _vscode_pyprof.collector.store.stack_table import InternedStack, SourceFrame, StackTable

ROOT = os.path.abspath(os.sep)
INTERNAL_DIR = os.path.join(ROOT, "ext", "_vscode_pyprof")
APP = os.path.join(ROOT, "work", "app.py")
LAUNCHER = os.path.join(INTERNAL_DIR, "launcher.py")
AGENT = os.path.join(INTERNAL_DIR, "agent.py")


class TestStackTable(unittest.TestCase):
    def setUp(self) -> None:
        self.table = StackTable(FrameClassifier([os.path.join(ROOT, "py", "lib")], [], INTERNAL_DIR))

    @staticmethod
    def frame(filename: str, funcname: str, line: int) -> FrameInfo:
        return FrameInfo((filename, LocationInfo((line, line, 0, 0)), funcname, None))

    def function_names(self, interned: InternedStack) -> list[str]:
        """Function names of a stack, root first."""
        stack = interned.stack_id
        frames = self.table.frames.rows(new_only=False)
        stacks = self.table.stacks.rows(new_only=False)
        names: list[str] = []
        while stack != StackTable.NO_STACK:
            stack, frame_id = stacks[stack]
            names.append(str(frames[frame_id][1]))
        return names[::-1]

    def test_intern_with_same_frames_returns_same_stack(self) -> None:
        path = [SourceFrame(APP, "main", 1), SourceFrame(APP, "work", 5)]

        first = self.table.intern(path, strip=False)
        second = self.table.intern(path, strip=False)

        self.assertEqual(first, second)

    def test_intern_with_shared_prefix_reuses_parent_stack(self) -> None:
        self.table.intern([SourceFrame(APP, "main", 1), SourceFrame(APP, "a", 5)], strip=False)
        self.table.intern([SourceFrame(APP, "main", 1), SourceFrame(APP, "b", 9)], strip=False)

        self.assertEqual(len(self.table.frames), 3)
        self.assertEqual(self.table.stacks.rows(new_only=False), [[-1, 0], [0, 1], [0, 2]])

    def test_intern_with_empty_path_returns_no_stack(self) -> None:
        self.assertEqual(self.table.intern([], strip=False), InternedStack(StackTable.NO_STACK, internal=True))

    def test_intern_records_frame_category(self) -> None:
        self.table.intern([SourceFrame(APP, "main", 1), SourceFrame("<native>", "<native>", 0)], strip=False)

        self.assertEqual(
            self.table.frames.rows(new_only=False),
            [[APP, "main", 1, int(FrameCategory.USER)], ["<native>", "<native>", 0, int(FrameCategory.SYNTHETIC)]],
        )

    def test_intern_with_strip_drops_launcher_frames_when_enabled(self) -> None:
        self.table.strip_launcher(True)

        stack = self.table.intern(
            [SourceFrame("<string>", "<module>", 1), SourceFrame(LAUNCHER, "run", 9), SourceFrame(APP, "main", 1)],
            strip=True,
        )

        self.assertListEqual(self.function_names(stack), ["main"])

    def test_intern_with_strip_keeps_launcher_frames_when_disabled(self) -> None:
        stack = self.table.intern([SourceFrame("<string>", "<module>", 1), SourceFrame(APP, "main", 1)], strip=True)

        self.assertListEqual(self.function_names(stack), ["<module>", "main"])

    def test_intern_sampled_reverses_leaf_first_frames(self) -> None:
        stack = self.table.intern_sampled([self.frame(APP, "work", 5), self.frame(APP, "main", 1)], strip=False)

        self.assertListEqual(self.function_names(stack), ["main", "work"])

    def test_intern_sampled_with_user_frames_is_not_internal(self) -> None:
        stack = self.table.intern_sampled([self.frame(APP, "main", 1)], strip=False)

        self.assertFalse(stack.internal)

    def test_intern_sampled_with_profiler_frame_is_internal(self) -> None:
        stack = self.table.intern_sampled([self.frame(AGENT, "run", 3)], strip=False)

        self.assertTrue(stack.internal)

    def test_intern_sampled_with_same_frames_but_other_strip_setting_is_interned_separately(self) -> None:
        self.table.strip_launcher(True)
        frames = [self.frame(APP, "main", 1), self.frame("<string>", "<module>", 1)]

        stripped = self.table.intern_sampled(frames, strip=True)
        unstripped = self.table.intern_sampled(frames, strip=False)

        self.assertListEqual(self.function_names(stripped), ["main"])
        self.assertListEqual(self.function_names(unstripped), ["<module>", "main"])


if __name__ == "__main__":
    unittest.main()
