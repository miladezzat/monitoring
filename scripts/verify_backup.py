#!/usr/bin/env python3
"""Round-trip all local volumes into a temporary project. Interrupts the source stack."""
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from common import CONFIG, ROOT, compose, query, ready, request, wait
from verify import send_probe, verify_probe


def main():
    source = CONFIG.get("COMPOSE_PROJECT_NAME", "monitoring")
    target = source + "-restore-" + secrets.token_hex(4)
    target_env = dict(CONFIG, COMPOSE_PROJECT_NAME=target)

    def target_compose(*arguments):
        subprocess.run(["docker", "compose", "--project-name", target, "--profile", "demo", *arguments],
                       cwd=ROOT, env=target_env, check=True)

    ready()
    probe = send_probe()
    verify_probe(probe)
    assert request("python", "/")["ok"]
    wait("backup fixture metric scraped", lambda: query('http_requests_total{service_name="example-python",route="/"}'))
    stamp = time.time()
    historical = 'http_requests_total{service_name="example-python",route="/"} @ ' + str(stamp)
    assert query(historical), "Run the demo integration check before the backup drill"
    uid = "backup-" + secrets.token_hex(6)
    request("grafana", "/api/dashboards/db", {"dashboard": {"uid": uid, "title": uid, "schemaVersion": 39, "panels": []}, "overwrite": False}, auth=True)
    begins = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    ends = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 3600))
    silence = request("alertmanager", "/api/v2/silences", {"matchers": [{"name": "alertname", "value": uid, "isRegex": False}], "startsAt": begins, "endsAt": ends, "createdBy": "local-backup-drill", "comment": "Restore verification"})["silenceID"]
    try:
        with tempfile.TemporaryDirectory(prefix="monitoring-backup-") as temporary:
            folder = Path(temporary) / "snapshot"
            subprocess.run([sys.executable, "scripts/backup.py", "backup", str(folder)], cwd=ROOT, env=dict(CONFIG), check=True)
            compose("stop")
            subprocess.run([sys.executable, "scripts/backup.py", "restore", str(folder)], cwd=ROOT, env=target_env, check=True)
            # A second restore must refuse to overwrite the existing target data.
            refusal = subprocess.run([sys.executable, "scripts/backup.py", "restore", str(folder)], cwd=ROOT, env=target_env, capture_output=True)
            assert refusal.returncode != 0 and b"Target volume is not empty" in refusal.stderr
            target_compose("up", "-d", "--build", "--wait", "--wait-timeout", "180")
            ready()
            verify_probe(probe)
            assert query(historical), "Historical metric missing from restored TSDB"
            assert request("grafana", "/api/dashboards/uid/" + uid, auth=True)["dashboard"]["uid"] == uid
            assert request("alertmanager", "/api/v2/silence/" + silence)["id"] == silence
            print("PASS restored metrics, logs, traces, user dashboard and silence; overwrite refusal", flush=True)
    finally:
        target_compose("down", "--volumes", "--remove-orphans")
        compose("--profile", "demo", "up", "-d", "--wait", "--wait-timeout", "180")
        ready()
        request("grafana", "/api/dashboards/uid/" + uid, method="DELETE", auth=True)
        request("alertmanager", "/api/v2/silence/" + silence, method="DELETE")


if __name__ == "__main__":
    main()
