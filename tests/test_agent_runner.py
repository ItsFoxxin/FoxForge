from foxforge.agent_runner import build_delegate_prompt


def test_delegate_prompt_names_role_and_task() -> None:
    prompt = build_delegate_prompt(
        role="architect",
        task="Add square",
        context="Existing calculator module",
    )

    assert "`architect`" in prompt
    assert "Add square" in prompt
    assert "Existing calculator module" in prompt
    assert "Do not perform the `architect` agent's work yourself." in prompt
