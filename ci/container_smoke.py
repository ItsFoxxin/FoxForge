"""Linux Docker persistence/security smoke. Synthetic credentials; no inference."""

from pathlib import Path
import os
import secrets
import subprocess
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
GATEWAY_IMAGE = "ghcr.io/tashfeenahmed/freellmapi@sha256:fe07ec5c57b4799922afde5d001eb1a3bb0d075e20400038b6c72718c9224efa"


def command(*args, expected=0):
    result = subprocess.run(args, capture_output=True, text=True, timeout=240)
    assert result.returncode == expected, result.stdout + result.stderr
    return result.stdout


def main():
    with tempfile.TemporaryDirectory(prefix="foxforge-container-") as temp:
        root = Path(temp)
        root.chmod(0o755)
        for name, uid in (("data", 10001), ("repos", 10001), ("config", 10001), ("gateway", 1000)):
            path = root / name
            path.mkdir(mode=0o750)
            subprocess.run(["sudo", "chown", f"{uid}:{uid}", str(path)], check=True)
        args = ["docker", "run", "--rm", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges:true",
                "--network=none", "--tmpfs=/tmp:rw,noexec,nosuid,size=32m", "--pids-limit=64", "--memory=512m",
                "-v", f"{root / 'data'}:/var/lib/foxforge/control-plane",
                "-v", f"{root / 'repos'}:/var/lib/foxforge/repos:ro", "-v", f"{root / 'config'}:/etc/foxforge:ro"]
        command(*args, "foxforge:0.4.0", "storage", "init")
        assert command(*args, "foxforge:0.4.0", "projects", "list").strip() == "[]"
        command(*args, "foxforge:0.4.0", "storage", "init", expected=1)
        command(*args, "foxforge:0.4.0", "watch", expected=2)
        probe = "import os; from pathlib import Path; assert os.geteuid()==10001; assert not os.access('/var/lib/foxforge/repos',os.W_OK); assert not os.access('/etc/foxforge',os.W_OK); assert not Path('/var/run/docker.sock').exists()"
        command(*args, "--entrypoint=python", "foxforge:0.4.0", "-c", probe)
        # Bypassing the CLI still cannot invoke legacy execution entrypoints.
        guard = "from foxforge.test_runner import run_tests; run_tests(None, 'must-not-execute')"
        command(*args, "--entrypoint=python", "foxforge:0.4.0", "-c", guard, expected=1)

        command(*args, "foxforge:0.4.0", "storage", "verify", "--directory", "/var/lib/foxforge/control-plane")
        seed = """from pathlib import Path
from foxforge.control_plane import ControlPlane
cp = ControlPlane()
p = cp.register_project(repository_id=17, repository='test/repo', local_path=Path('/var/lib/foxforge/repos/test'), default_branch='dev')
t, _ = cp.authorize_and_create_task(p, {'number': 1, 'revision': 'a'*64}, actor_id=5, event_id=91)
cp.update_task(t['id'], state='active', activity='planning')
out = cp.artifacts(t['id'])
(out/'plan.md').write_text('Synthetic planning artifact', encoding='utf-8')
cp.update_task(t['id'], state='awaiting_human_review', activity='idle', artifact_dir=out)
print(t['id'])
"""
        task_id = command(*args, "--entrypoint=python", "foxforge:0.4.0", "-c", seed).strip()
        assert "awaiting_human_review" in command(*args, "foxforge:0.4.0", "tasks", "show", task_id)
        command(*args, "foxforge:0.4.0", "storage", "verify", "--directory", "/var/lib/foxforge/control-plane")
        # The real pinned gateway must boot under the shipped non-root/RO policy.
        env = root / "gateway.env"
        env.write_text("ENCRYPTION_KEY=" + secrets.token_hex(32) + "\nNODE_ENV=production\n", encoding="utf-8")
        env.chmod(0o600)
        os.environ["FOXFORGE_ENV_FILE"] = str(env)
        os.environ["FREELLMAPI_ENV_FILE"] = str(env)
        command("docker", "compose", "--profile", "cli", "config", "--quiet")
        name = "foxforge-ci-gateway-" + secrets.token_hex(4)
        command("docker", "run", "-d", "--name", name, "--user=1000:1000", "--read-only", "--cap-drop=ALL",
                "--security-opt=no-new-privileges:true", "--network=none", "--memory=1g", "--pids-limit=128",
                "--tmpfs=/tmp:rw,noexec,nosuid,size=64m", "--env-file", str(env),
                "-v", f"{root / 'gateway'}:/app/server/data", GATEWAY_IMAGE)
        try:
            for _ in range(30):
                probe = subprocess.run(["docker", "exec", name, "node", "-e",
                    "fetch('http://127.0.0.1:3001/api/ping').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"], capture_output=True)
                if probe.returncode == 0:
                    break
                time.sleep(2)
            else:
                raise AssertionError("Pinned gateway did not become ready under the restricted deployment")
            command("docker", "exec", name, "node", "-e",
                "fetch('http://127.0.0.1:3001/v1/models',{headers:{Authorization:'Bearer intentionally-invalid'}}).then(r=>process.exit(r.status===401?0:1))")
        finally:
            command("docker", "rm", "-f", name)
        print("Non-root/RO container, persisted SQLite, disabled execution, real gateway readiness and auth rejection verified")


if __name__ == "__main__":
    main()
