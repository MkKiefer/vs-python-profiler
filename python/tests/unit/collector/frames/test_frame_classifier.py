import os
import sys
import sysconfig
import tempfile
import unittest

from _vspyprof import PACKAGE_DIR
from _vspyprof.collector.frames.frame_classifier import FrameCategory, FrameClassifier


class TestFrameClassifier(unittest.TestCase):
    def setUp(self) -> None:
        self.root = os.path.abspath(os.sep)
        self.std_dir = os.path.join(self.root, "py", "lib")
        self.lib_dir = os.path.join(self.std_dir, "site-packages")
        self.internal_dir = os.path.join(self.root, "ext", "_vspyprof")
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

    @unittest.skipIf(sys.platform == "win32", "creating symlinks needs privileges on Windows")
    def test_category_with_stdlib_reached_through_symlink_returns_stdlib(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            real_std = os.path.join(tmp, "framework", "lib")
            os.makedirs(os.path.join(real_std, "json"))
            linked_prefix = os.path.join(tmp, "toolcache")
            os.symlink(os.path.join(tmp, "framework"), linked_prefix)
            linked_std = os.path.join(linked_prefix, "lib")
            for std_dir, filename in ((linked_std, real_std), (real_std, linked_std)):
                with self.subTest(std_dir=std_dir):
                    classifier = FrameClassifier([std_dir], [], self.internal_dir)

                    category = classifier.category(os.path.join(filename, "json", "decoder.py"))

                    self.assertEqual(category, FrameCategory.STDLIB)

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

        self.assertEqual(
            classifier.category(os.__file__),
            FrameCategory.STDLIB,
            msg=f"{os.__file__} not below the stdlib of {sysconfig.get_paths()} (base prefix {sys.base_prefix})",
        )
        self.assertTrue(classifier.is_internal(os.path.join(PACKAGE_DIR, "agent.py")))


if __name__ == "__main__":
    unittest.main()
