"""Readiness probe shared by Compose; no shell tools needed in backend images."""
import urllib.request

for endpoint in ["grafana:3000/api/health", "prometheus:9090/-/ready", "loki:3100/ready",
                 "tempo:3200/ready", "alloy:12345/-/ready", "alertmanager:9093/-/ready"]:
    with urllib.request.urlopen("http://" + endpoint, timeout=2) as response:
        if response.status != 200:
            raise SystemExit(1)
