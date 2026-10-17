# FoxForge Repository Instructions

FoxForge is an existing local-first deterministic orchestrator for Qwen Code.
Preserve its Python-owned orchestration and six project-agent boundaries.
Only the calculator example and temporary test fixtures are disposable targets.
Do not operate on unrelated repositories.

Rules:

- Read existing code before editing.
- Make only changes required by the task.
- Run pytest after modifying code.
- If tests fail because of your change, diagnose and repair them.
- Do not use network access.
- Do not delete files unless explicitly required.
- Do not modify Git configuration.
- Do not commit or push.
