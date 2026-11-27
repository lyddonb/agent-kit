import unittest

from labels import joined


class JoinedTest(unittest.TestCase):
    def test_labels_joined(self):
        self.assertEqual(joined(["docs", "bug", "docs"]), "bug, docs")

    def test_one_label(self):
        self.assertEqual(joined(["bug"]), "bug")


if __name__ == "__main__":
    unittest.main()
