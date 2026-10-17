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

For Dead Circuit, the intended authoritative validation command is:

```text
python tools/dev.py validate
```

FoxForge should branch from the latest `origin/dev` and create a short-lived
`foxforge/<task>` branch.
