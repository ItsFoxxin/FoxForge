from foxforge.git_manager import slugify_task


def test_slugify_task() -> None:
    assert (
        slugify_task("Add Blood Capacitor Item!")
        == "add-blood-capacitor-item"
    )


def test_slugify_task_has_fallback() -> None:
    assert slugify_task("!!!") == "task"


def test_slugify_task_truncates() -> None:
    slug = slugify_task("A" * 200)
    assert len(slug) <= 48
