"""Local configuration and bounded HTTP helpers shared by verification tools."""
import base64
import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def settings():
    config = {}
    if (ROOT / ".env").exists():
        for line in (ROOT / ".env").read_text().splitlines():
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                config[key] = value
    config.update(os.environ)
    return config


CONFIG = settings()
PORTS = {"grafana": ("GRAFANA_PORT", 3001), "prometheus": ("PROMETHEUS_PORT", 9090),
         "loki": ("LOKI_PORT", 3100), "tempo": ("TEMPO_PORT", 3200), "alloy": ("ALLOY_PORT", 12345),
         "otlp": ("OTLP_HTTP_PORT", 4318), "alertmanager": ("ALERTMANAGER_PORT", 9093),
         "nestjs": ("NESTJS_PORT", 3000), "python": ("PYTHON_PORT", 3002)}


def url(service, path=""):
    key, default = PORTS[service]
    return f"http://127.0.0.1:{CONFIG.get(key, default)}{path}"


def request(service, path="", data=None, method=None, auth=False):
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if auth:
        credential = CONFIG.get("GRAFANA_ADMIN_USER", "admin") + ":" + CONFIG.get("GRAFANA_ADMIN_PASSWORD", "")
        headers["Authorization"] = "Basic " + base64.b64encode(credential.encode()).decode()
    req = urllib.request.Request(url(service, path), data=json.dumps(data).encode() if data is not None else None, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=5) as response:
        body = response.read().decode()
        return json.loads(body) if body and body[0] in "[{" else body


def wait(label, predicate, timeout=120):
    deadline = time.monotonic() + timeout
    last_error = "condition is not yet satisfied"
    while time.monotonic() < deadline:
        try:
            value = predicate()
            if value:
                print("PASS " + label, flush=True)
                return value
        except (OSError, ValueError, urllib.error.HTTPError) as error:
            last_error = str(error)
        time.sleep(1)
    raise RuntimeError(f"Timed out waiting for {label}: {last_error}")


def compose(*arguments, capture=False):
    command = ["docker", "compose", "--project-name", CONFIG.get("COMPOSE_PROJECT_NAME", "monitoring"), *arguments]
    return subprocess.run(command, cwd=ROOT, check=True, text=True, capture_output=capture, env=dict(CONFIG))


def query(expression):
    response = request("prometheus", "/api/v1/query?" + urllib.parse.urlencode({"query": expression}))
    if response.get("status") != "success":
        raise RuntimeError("Prometheus query failed")
    return response["data"]["result"]


def ready():
    for service, path in [("grafana", "/api/health"), ("prometheus", "/-/ready"), ("loki", "/ready"),
                          ("tempo", "/ready"), ("alloy", "/-/ready"), ("alertmanager", "/-/ready")]:
        wait(service + " ready", lambda service=service, path=path: request(service, path))
