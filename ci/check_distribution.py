"""Exercise the built wheel outside the checkout, without network or models."""

from pathlib import Path
import os
import subprocess
import shutil
import tarfile
import tempfile
import venv
import zipfile


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    wheel, = (root / "dist").glob("*.whl")
    sdist, = (root / "dist").glob("*.tar.gz")
    with tarfile.open(sdist) as archive:
        sources = archive.getnames()
        assert any(name.endswith("/tests/conftest.py") for name in sources)
        assert any(name.endswith("/ci/check_distribution.py") for name in sources)
        assert not any("__pycache__" in name or ".pytest_cache" in name or "VALIDATION.txt" in name for name in sources)
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        assert len([name for name in names if "/qwen-agents/" in name and name.endswith(".md")]) == 6
        assert not any("__pycache__" in name or ".pytest_cache" in name or "VALIDATION.txt" in name for name in names)
    with tempfile.TemporaryDirectory(prefix="foxforge-package-") as temp:
        directory = Path(temp)
        environment = directory / "venv"
        venv.EnvBuilder(with_pip=True).create(environment)
        bin_dir = environment / ("Scripts" if os.name == "nt" else "bin")
        python = bin_dir / ("python.exe" if os.name == "nt" else "python")
        console = bin_dir / ("foxforge.exe" if os.name == "nt" else "foxforge")
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env.pop("DISCORD_WEBHOOK_URL", None)
        def check(*args):
            subprocess.run([str(arg) for arg in args], cwd=directory, env=env, check=True, timeout=120)
        check(python, "-m", "pip", "install", "--no-index", "--no-deps", wheel)
        check(python, "-c", "import importlib, pkgutil, foxforge; [importlib.import_module(m.name) for m in pkgutil.walk_packages(foxforge.__path__, foxforge.__name__ + '.')]")
        for module in ("foxforge", "foxforge.reporter_dispatch", "foxforge.notify_status", "foxforge.notifier"):
            check(python, "-m", module, "--help")
        check(console, "--help")
        failure = subprocess.run(
            [str(python), "-m", "foxforge", "--repo", str(directory), "--task", "validation", "--test-command", "pytest", "--skip-discord"],
            cwd=directory, env=env, capture_output=True, text=True, timeout=120,
        )
        assert failure.returncode == 1 and "Traceback" not in failure.stderr
        assert (environment / "share" / "foxforge" / "qwen-agents" / "reporter.md").is_file()
        assert (environment / "share" / "foxforge" / "scripts" / "install-target.ps1").is_file()
        powershell = shutil.which("pwsh")
        if powershell:
            target = directory / "target with spaces"
            target.mkdir()
            check(powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                  environment / "share" / "foxforge" / "scripts" / "install-target.ps1",
                  "-RepoPath", target)
            assert len(list((target / ".qwen" / "agents").glob("*.md"))) == 6
        print("Installed wheel, assets, imports, and entrypoints verified")


if __name__ == "__main__":
    main()
