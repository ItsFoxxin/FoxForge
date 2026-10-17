from foxforge.test_runner import (
    count_test_definitions,
    is_likely_test_file,
)


def test_count_python_test_definitions() -> None:
    text = """
def test_one():
    pass

def helper():
    pass

def test_two():
    pass
"""
    assert count_test_definitions(text) == 2


def test_count_gdscript_test_definitions() -> None:
    text = """
func test_one():
    pass

func helper():
    pass

func test_two():
    pass
"""
    assert count_test_definitions(text) == 2


def test_likely_test_file() -> None:
    assert is_likely_test_file("tests/test_math.py")
    assert is_likely_test_file("test_player.gd")
    assert not is_likely_test_file("player.gd")
