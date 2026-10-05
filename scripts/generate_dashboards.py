#!/usr/bin/env python3
"""Keep small provisioned dashboards readable and reproducible."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def panel(title, expr, unit="short", kind="timeseries", source="prometheus"):
    return {"title": title, "type": kind, "datasource": {"uid": source},
            "targets": [{"refId": "A", "expr": expr}],
            "fieldConfig": {"defaults": {"unit": unit}, "overrides": []},
            "options": {}}


def dashboard(uid, title, panels, service=False):
    for index, item in enumerate(panels):
        item.update(id=index + 1, gridPos={"x": (index % 2) * 12, "y": (index // 2) * 8, "w": 12, "h": 8})
    variables = []
    if service:
        variables.append({"name": "service", "label": "Service", "type": "query", "datasource": {"uid": "prometheus"},
                          "query": "label_values(http_requests_total, service_name)", "refresh": 1,
                          "multi": True, "includeAll": True, "allValue": ".*", "current": {"text": "All", "value": "$__all"}})
    return {"uid": uid, "title": title, "schemaVersion": 39, "version": 1, "tags": ["monitoring"],
            "editable": False, "timezone": "browser", "refresh": "10s", "time": {"from": "now-15m", "to": "now"},
            "templating": {"list": variables}, "panels": panels}


SELECTOR = 'service_name=~"$service"'
DOCUMENTS = {
    "application.json": dashboard("monitoring-application", "Application traffic and logs", [
        panel("Requests per second", f'sum by (service_name) (rate(http_requests_total{{{SELECTOR}}}[1m]))', "reqps"),
        panel("Server error ratio", f'sum by (service_name) (rate(http_requests_total{{{SELECTOR},status_code=~"5.."}}[5m])) / sum by (service_name) (rate(http_requests_total{{{SELECTOR}}}[5m]))', "percentunit"),
        panel("P95 request duration", f'histogram_quantile(0.95, sum by (le, service_name) (rate(http_request_duration_seconds_bucket{{{SELECTOR}}}[5m])))', "s"),
        panel("Requests by route", f'sum by (service_name, route, status_code) (increase(http_requests_total{{{SELECTOR}}}[5m]))'),
        panel("Application logs", f'{{{SELECTOR}}} | json', kind="logs", source="loki"),
        panel("Dropped application log records", f'sum by (service_name) (rate(application_log_dropped_total{{{SELECTOR}}}[5m]))', "ops"),
    ], True),
    "runtime.json": dashboard("monitoring-runtime", "Application runtime", [
        panel("Resident memory", f'process_resident_memory_bytes{{{SELECTOR}}}', "bytes"),
        panel("CPU cores used", f'rate(process_cpu_seconds_total{{{SELECTOR}}}[1m])'),
        panel("Node.js heap used", f'nodejs_heap_size_used_bytes{{{SELECTOR}}}', "bytes"),
        panel("Node.js event loop lag", f'nodejs_eventloop_lag_p99_seconds{{{SELECTOR}}}', "s"),
    ], True),
    "pipeline.json": dashboard("monitoring-pipeline", "Monitoring pipeline health", [
        panel("Backend availability", 'up{job=~"prometheus|grafana|alloy|loki|tempo|alertmanager"}', kind="stat"),
        panel("Collector export queue", 'otelcol_exporter_queue_size'),
        panel("File log drops", 'sum(rate(loki_write_dropped_entries_total[5m]))', "ops"),
        panel("Active metric series", 'prometheus_tsdb_head_series'),
        panel("Collector export queue utilization", 'otelcol_exporter_queue_size{data_type=~"traces|logs"} / otelcol_exporter_queue_capacity{data_type=~"traces|logs"}', "percentunit"),
        panel("Monitoring process memory", 'process_resident_memory_bytes{job=~"prometheus|grafana|alloy|loki|tempo|alertmanager"}', "bytes"),
    ]),
}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for name, document in DOCUMENTS.items():
        path = ROOT / "grafana/dashboards" / name
        content = json.dumps(document, indent=2) + "\n"
        if args.check:
            if not path.exists() or path.read_text() != content:
                raise SystemExit(f"Dashboard is out of date: {path.name}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
    print("Dashboard definitions match." if args.check else "Generated three dashboards.")
