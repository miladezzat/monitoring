#!/usr/bin/env python3
"""Validate configuration with the same pinned binaries used at runtime."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from common import ROOT


def main():
    env = dict(os.environ, GRAFANA_ADMIN_PASSWORD="validation-only")
    base = ["docker", "compose", "--project-name", "monitoring-config-check", "--profile", "demo"]
    config = json.loads(subprocess.check_output([*base, "config", "--format", "json"], cwd=ROOT, env=env))
    lock = json.loads((ROOT / "image-lock.json").read_text())
    for name, service in config["services"].items():
        image = service.get("image")
        if image:
            tag, digest = image.split("@", 1)
            assert lock.get(tag) == digest, f"Unpinned or unlocked image: {name}"
        assert all(port.get("host_ip") == "127.0.0.1" for port in service.get("ports", [])), f"Nonlocal published port: {name}"
        assert int(service.get("mem_limit", 0)) > 0, f"Missing memory bound: {name}"
    for path in ROOT.glob("examples/*/Dockerfile"):
        for image in re.findall(r"^FROM (\S+)", path.read_text(), re.MULTILINE):
            tag, digest = image.split("@", 1)
            assert lock.get(tag) == digest, f"Unlocked example base image: {path}"
    print("PASS compose ports, memory bounds, and image locks", flush=True)
    subprocess.run([sys.executable, "scripts/generate_dashboards.py", "--check"], cwd=ROOT, check=True)
    commands = [
        ["run", "--rm", "--no-deps", "--entrypoint", "promtool", "prometheus", "check", "config", "/etc/prometheus/prometheus.yml"],
        ["run", "--rm", "--no-deps", "-v", str(ROOT / "tests") + ":/tests:ro", "--entrypoint", "promtool", "prometheus", "test", "rules", "/tests/rules.yml"],
        ["run", "--rm", "--no-deps", "--entrypoint", "amtool", "alertmanager", "check-config", "/etc/alertmanager/config.yml"],
        ["run", "--rm", "--no-deps", "loki", "-config.file=/etc/loki/config.yaml", "-verify-config=true"],
        ["run", "--rm", "--no-deps", "alloy", "validate", "--stability.level=public-preview", "/etc/alloy/config.alloy"],
    ]
    try:
        for command in commands:
            subprocess.run([*base, *command], cwd=ROOT, env=env, check=True)
    finally:
        subprocess.run([*base, "down", "--volumes"], cwd=ROOT, env=env, check=True, stdout=subprocess.DEVNULL)
    print("PASS pinned service validators and alert rule tests", flush=True)


if __name__ == "__main__":
    main()
