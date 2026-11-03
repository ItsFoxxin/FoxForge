# Target Repository Setup

A repository used by FoxForge needs project-level Qwen agents.

From the FoxForge repository:

```powershell
.\scripts\install-target.ps1 -RepoPath C:\Projects\YourProject
```

This installs:

```text
.qwen/
└── agents/
    ├── architect.md
    ├── implementer.md
    ├── tester.md
    ├── reviewer.md
    ├── helper.md
    └── reporter.md
```

Project-specific instructions may be added to the agent files, but preserve their
role boundaries.

The target repo should also have its own project instructions, architecture docs,
and authoritative test command.

For a Python target, an example authoritative validation command is:

```text
python -m pytest -v
```

FoxForge should branch from the latest `origin/dev` and create a short-lived
`foxforge/<task>` branch.

Existing agent definitions are preserved unless you explicitly pass -Force.
For custom validators, emit a supported authoritative test summary as described in README.md.


Canonical wrapper settings are templates/qwen-settings.json. The installer creates
settings only when absent; project-specific settings are preserved. Tests/CI do
not require a checked-in .qwen directory, but target Qwen execution requires its
installed role definitions. Publishing uses --publish-pr and origin/dev only.

