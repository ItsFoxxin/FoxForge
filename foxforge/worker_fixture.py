"""Immutable, synthetic repository. Nothing here fetches or executes a live repo."""
import hashlib

FILES = {
    "calculator.py": b"def add(a, b):\n    return a + b\n",
    "test_calculator.py": b"import unittest\nfrom calculator import add\nclass TestCalculator(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n",
}
TEST_UPDATE = FILES["test_calculator.py"] + b"    def test_negative(self):\n        self.assertEqual(add(-2, 3), 1)\n"


def git_object(kind, content):
    return hashlib.sha1(kind.encode() + b" " + str(len(content)).encode() + b"\0" + content).digest()


def repository():
    # A real deterministic Git commit object, reproducible with git hash-object.
    tree = b"".join(b"100644 " + name.encode() + b"\0" + git_object("blob", body) for name, body in sorted(FILES.items()))
    commit = b"tree " + git_object("tree", tree).hex().encode() + b"\nauthor FoxForge Fixture <fixture@example.invalid> 0 +0000\ncommitter FoxForge Fixture <fixture@example.invalid> 0 +0000\n\nDisposable calculator fixture\n"
    return {"id": 1, "name": "foxforge-fixtures/calculator", "base_sha": git_object("commit", commit).hex()}


PROFILE_DIGEST = hashlib.sha256(b"FoxForge mock-fixture QA profile v1; no live runtime").hexdigest()
