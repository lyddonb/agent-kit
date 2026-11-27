import unittest

from owners import listed


class ListedTest(unittest.TestCase):
    def test_owners_listed(self):
        self.assertEqual(listed(["sam", "ana", "sam"]), "@ana @sam")


if __name__ == "__main__":
    unittest.main()
