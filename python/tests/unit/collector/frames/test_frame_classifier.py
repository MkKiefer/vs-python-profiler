import os
import unittest

from _vscode_pyprof import PACKAGE_DIR
from _vscode_pyprof.collector.frames.frame_classifier import FrameCategory, FrameClassifier


class TestFrameClassifier(unittest.TestCase):
    def setUp(self) -> None:
        self.root = os.path.abspath(os.sep)
        self.std_dir = os.path.join(self.root, "py", "lib")
        self.lib_dir = os.path.join(self.std_dir, "site-packages")
        self.internal_dir = os.path.join(self.root, "ext", "_vscode_pyprof")
        self.classifier = FrameClassifier([self.std_dir], [self.lib_dir], self.internal_dir)

    def test_category_with_site_packages_file_returns_library(self) -> None:
        filename = os.path.join(self.lib_dir, "requests", "api.py")

        self.assertEqual(self.classifier.category(filename), FrameCategory.LIBRARY)

    def test_category_with_stdlib_file_returns_stdlib(self) -> None:
        filename = os.path.join(self.std_dir, "json", "decoder.py")

        self.assertEqual(self.classifier.category(filename), FrameCategory.STDLIB)

    def test_category_with_project_file_returns_user(self) -> None:
        filename = os.path.join(self.root, "work", "app.py")

        self.assertEqual(self.classifier.category(filename), FrameCategory.USER)

    def test_category_with_synthetic_frame_returns_synthetic(self) -> None:
        for filename in ("<native>", "<frozen importlib._bootstrap>", "~", ""):
            with self.subTest(filename=filename):
                self.assertEqual(self.classifier.category(filename), FrameCategory.SYNTHETIC)

    def test_category_with_sibling_directory_sharing_prefix_returns_user(self) -> None:
        filename = os.path.join(self.root, "py", "library", "mine.py")

        self.assertEqual(self.classifier.category(filename), FrameCategory.USER)

    def test_is_internal_with_profiler_file_returns_true(self) -> None:
        filename = os.path.join(self.internal_dir, "agent.py")

        self.assertTrue(self.classifier.is_internal(filename))

    def test_is_internal_with_user_file_returns_false(self) -> None:
        filename = os.path.join(self.root, "work", "agent.py")

        self.assertFalse(self.classifier.is_internal(filename))

    def test_is_launcher_frame_with_bootstrap_files_returns_true(self) -> None:
        launcher_files = (
            "<string>",
            "<frozen runpy>",
            os.path.join(self.std_dir, "runpy.py"),
            os.path.join(self.internal_dir, "launcher.py"),
        )
        for filename in launcher_files:
            with self.subTest(filename=filename):
                self.assertTrue(self.classifier.is_launcher_frame(filename))

    def test_is_launcher_frame_with_file_ending_in_runpy_returns_false(self) -> None:
        filename = os.path.join(self.root, "work", "myrunpy.py")

        self.assertFalse(self.classifier.is_launcher_frame(filename))

    def test_launcher_prefix_length_counts_only_leading_launcher_frames(self) -> None:
        user_file = os.path.join(self.root, "work", "app.py")
        filenames = [
            "<string>",
            os.path.join(self.internal_dir, "launcher.py"),
            "<frozen runpy>",
            user_file,
            "<string>",
        ]

        self.assertEqual(self.classifier.launcher_prefix_length(filenames), 3)

    def test_for_running_interpreter_classifies_stdlib_and_own_package(self) -> None:
        classifier = FrameClassifier.for_running_interpreter()

        self.assertEqual(classifier.category(os.__file__), FrameCategory.STDLIB)
        self.assertTrue(classifier.is_internal(os.path.join(PACKAGE_DIR, "agent.py")))


if __name__ == "__main__":
    unittest.main()
