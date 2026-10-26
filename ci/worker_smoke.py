"""Real Linux container checks, synthetic fixtures only. No privileged sandbox."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
from uuid import uuid4

from foxforge import worker_protocol as p
from foxforge.worker_demo import exercise
from foxforge.worker_docker import DockerSandbox


def main():
    sandbox = DockerSandbox()
    with tempfile.TemporaryDirectory(prefix="foxforge-worker-ci-") as temp:
        root = Path(temp)
        expected = {"success": "succeeded", "readonly-denial": "failed", "unavailable": "failed",
                    "output": "failed", "memory": "failed", "disk": "failed", "network": "failed",
                    "processes": "failed", "deadline": "interrupted"}
        for scenario, state in expected.items():
            result = exercise(root / scenario, sandbox, scenario=scenario, duration=2 if scenario == "deadline" else 60)
            assert result["state"] == state, result
            if scenario in {"disk", "network", "processes"}:
                assert result["result"]["data"]["reason"] == {"disk": "disk_limited", "network": "network_denied", "processes": "process_limited"}[scenario], result
            print(f"Worker real-container scenario {scenario}: {state}")
        cancel = threading.Event()
        timer = threading.Timer(1, cancel.set)
        timer.start()
        try:
            result = exercise(root / "cancel", sandbox, scenario="deadline", cancelled=cancel.is_set)
            assert result["state"] == "cancelled", result
        finally:
            timer.cancel()
        # Inspect the actual security envelope and fresh workspace in a new container.
        import time
        scope = {"budgets": dict(p.MAXIMA), "expires_at": int(time.time())+30}
        name = "foxforge-fixture-" + uuid4().hex
        command = sandbox.command(scope, name)
        probe = "import os;from pathlib import Path;assert os.getuid()==11001;assert not os.access('/runner',os.W_OK);assert not Path('/var/run/docker.sock').exists();assert not Path('/etc/foxforge').exists();assert not list(Path('/workspace').iterdir());assert 'FOXFORGE_TEST_SECRET' not in os.environ;assert not os.access('/',os.W_OK)"
        os.environ["FOXFORGE_TEST_SECRET"] = "synthetic-must-not-inherit"
        try:
            subprocess.run(command[:-1]+["--entrypoint=python", sandbox.image, "-I", "-c", probe], check=True, capture_output=True, timeout=30)
        finally:
            os.environ.pop("FOXFORGE_TEST_SECRET", None)
            sandbox.remove(name)
        remaining = subprocess.run([sandbox.exe, "ps", "-aq", "--filter=label=foxforge.prototype=true"], capture_output=True, text=True, check=True, timeout=15)
        assert not remaining.stdout.strip(), "Prototype containers were not cleaned up"
    print("Worker boundaries, mock planning, real tests, scope denial, resource limits, cancellation and cleanup verified")


if __name__ == "__main__":
    main()
