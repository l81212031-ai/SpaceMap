import os
import tempfile
import threading
import unittest

from spacemap import format_size, scan_directory


class FormatSizeTests(unittest.TestCase):
    def test_bytes(self):
        self.assertEqual(format_size(12), "12.0 B")

    def test_kilobytes(self):
        self.assertEqual(format_size(1024), "1.0 KB")

    def test_megabytes(self):
        self.assertEqual(format_size(1024 ** 2), "1.0 MB")


class ScanDirectoryTests(unittest.TestCase):
    def test_counts_files_and_folders_and_sums_sizes(self):
        with tempfile.TemporaryDirectory() as root:
            nested = os.path.join(root, "nested")
            os.mkdir(nested)
            with open(os.path.join(root, "a.txt"), "wb") as stream:
                stream.write(b"hello")
            with open(os.path.join(nested, "b.bin"), "wb") as stream:
                stream.write(b"1234567")

            result = scan_directory(root)

            self.assertEqual(result["file_count"], 2)
            self.assertEqual(result["folder_count"], 1)
            self.assertEqual(result["root"]["size"], 12)
            self.assertEqual(result["nodes"][nested]["size"], 7)

    def test_cancelled_scan_returns_none(self):
        with tempfile.TemporaryDirectory() as root:
            event = threading.Event()
            event.set()
            self.assertIsNone(scan_directory(root, event))

    def test_invalid_directory_raises(self):
        with self.assertRaises(NotADirectoryError):
            scan_directory(os.path.join(tempfile.gettempdir(), "space-map-does-not-exist"))


if __name__ == "__main__":
    unittest.main()
