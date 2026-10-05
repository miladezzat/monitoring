#!/usr/bin/env python3
"""Query actual storage; optionally interrupt only the selected local Compose project."""
import argparse
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from common import CONFIG, compose, query, ready, request, url, wait


def send_probe():
    trace_id, span_id, marker = secrets.token_hex(16), secrets.token_hex(8), secrets.token_hex(12)
    now = time.time_ns()
    resource = {"attributes": [{"key": "service.name", "value": {"stringValue": "protocol-smoke"}}]}
    traces = {"resourceSpans": [{"resource": resource, "scopeSpans": [{"scope": {"name": "protocol-smoke"}, "spans": [{
        "traceId": trace_id, "spanId": span_id, "name": marker, "kind": 2,
        "startTimeUnixNano": str(now), "endTimeUnixNano": str(now + 1000000),
    }]}]}]}
    logs = {"resourceLogs": [{"resource": resource, "scopeLogs": [{"scope": {"name": "protocol-smoke"}, "logRecords": [{
        "timeUnixNano": str(now), "severityNumber": 9, "severityText": "INFO",
        "body": {"stringValue": json.dumps({"message": marker, "trace_id": trace_id})},
        "traceId": trace_id, "spanId": span_id,
    }]}]}]}
    for signal, payload in [("traces", traces), ("logs", logs)]:
        response = request("otlp", "/v1/" + signal, payload)
        partial = response.get("partialSuccess", {}) if isinstance(response, dict) else {}
        assert not any(partial.get(key, 0) not in (0, "0") for key in ("rejectedSpans", "rejectedLogRecords")), "OTLP data rejected"
    return trace_id, marker


def trace_exists(trace_id):
    document = request("tempo", "/api/traces/" + trace_id)
    return bool(document.get("batches") or document.get("resourceSpans"))


def log_exists(service, marker):
    expression = '{service_name="' + service + '"} |= "' + marker + '"'
    document = request("loki", "/loki/api/v1/query_range?" + urllib.parse.urlencode({"query": expression, "limit": 100}))
    return any(stream.get("values") for stream in document["data"]["result"])


def verify_probe(probe):
    trace_id, marker = probe
    wait("protocol-neutral trace stored", lambda: trace_exists(trace_id))
    wait("protocol-neutral OTLP log stored", lambda: log_exists("protocol-smoke", marker))


def check_examples():
    probes = []
    for language in ("nestjs", "python"):
        wait(language + " ready", lambda language=language: request(language, "/health"))
        for path in ("/", "/slow", "/error", "/unmatched-" + secrets.token_hex(6)):
            try:
                with urllib.request.urlopen(url(language, path), timeout=5) as response:
                    trace_id = response.headers.get("X-Trace-Id")
            except urllib.error.HTTPError as error:
                assert error.code == (500 if path == "/error" else 404)
                trace_id = error.headers.get("X-Trace-Id")
            if path == "/":
                assert trace_id and len(trace_id) == 32, language + " trace context missing"
                probes.append((language, trace_id))
        service = "example-" + language
        wait(language + " metric scraped", lambda service=service: query('http_requests_total{service_name="' + service + '",route="/"}'))
        # Probe arbitrary URLs without allowing a unique route label per URL.
        assert not query('http_requests_total{service_name="' + service + '",route=~"/unmatched-.*"}')
    for language, trace_id in probes:
        wait(language + " SDK trace stored", lambda trace_id=trace_id: trace_exists(trace_id))
        wait(language + " file log correlates with trace", lambda language=language, trace_id=trace_id: log_exists("example-" + language, trace_id))


def check_grafana():
    for uid in ("prometheus", "loki", "tempo"):
        document = request("grafana", "/api/datasources/uid/" + uid, auth=True)
        assert document["uid"] == uid
    for uid in ("monitoring-application", "monitoring-runtime", "monitoring-pipeline"):
        assert request("grafana", "/api/dashboards/uid/" + uid, auth=True)["dashboard"]["panels"]
    field = request("grafana", "/api/datasources/uid/loki", auth=True)["jsonData"]["derivedFields"][0]
    assert field["datasourceUid"] == "tempo" and field["url"] == "${__value.raw}"
    print("PASS provisioned dashboards, datasource UIDs, and trace links", flush=True)


def recover():
    print("Testing a backend outage and collector restart in project " + CONFIG.get("COMPOSE_PROJECT_NAME", "monitoring"), flush=True)
    try:
        compose("stop", "loki", "tempo")
        probe = send_probe()
        wait("outage data reached exporter queue", lambda: query('sum(otelcol_exporter_queue_size) > 0'))
        # Successful requests while telemetry storage is unavailable.
        for language in ("nestjs", "python"):
            start = time.monotonic()
            assert request(language, "/")["ok"]
            assert time.monotonic() - start < 3, "Telemetry outage blocked a request"
        wait("backend outage alert firing", lambda: any(a["labels"].get("alertname") == "BackendDown" and a["state"] == "firing" for a in request("prometheus", "/api/v1/alerts")["data"]["alerts"]))
        wait("alert reached Alertmanager", lambda: any(a["labels"].get("alertname") == "BackendDown" for a in request("alertmanager", "/api/v2/alerts")))
        # SIGKILL bypasses the collector's shutdown flush, exercising disk queues.
        compose("kill", "-s", "SIGKILL", "alloy")
    finally:
        compose("up", "-d", "loki", "tempo", "alloy")
    ready()
    verify_probe(probe)
    wait("backend alerts resolved", lambda: not any(a["labels"].get("alertname") == "BackendDown" for a in request("prometheus", "/api/v1/alerts")["data"]["alerts"]))
    wait("export queues drained", lambda: query('sum(otelcol_exporter_queue_size) == 0'))

    # Preserve a historical metric, a stored trace/log, a user dashboard and silence.
    stamp = time.time()
    historical = 'http_requests_total{service_name="example-python",route="/"} @ ' + str(stamp)
    assert query(historical)
    uid = "smoke-" + secrets.token_hex(6)
    request("grafana", "/api/dashboards/db", {"dashboard": {"uid": uid, "title": uid, "schemaVersion": 39, "panels": []}, "overwrite": False}, auth=True)
    ends = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 3600))
    begins = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    silence = request("alertmanager", "/api/v2/silences", {"matchers": [{"name": "alertname", "value": uid, "isRegex": False}], "startsAt": begins, "endsAt": ends, "createdBy": "local-smoke-test", "comment": "Persistence verification"})["silenceID"]
    try:
        compose("--profile", "demo", "up", "-d", "--force-recreate", "--no-build")
        ready()
        verify_probe(probe)
        assert query(historical), "Historical metrics lost after recreation"
        assert request("grafana", "/api/dashboards/uid/" + uid, auth=True)["dashboard"]["uid"] == uid
        assert request("alertmanager", "/api/v2/silence/" + silence)["id"] == silence
        print("PASS metrics, logs, traces, Grafana state and Alertmanager silence survived recreation", flush=True)
    finally:
        request("grafana", "/api/dashboards/uid/" + uid, method="DELETE", auth=True)
        request("alertmanager", "/api/v2/silence/" + silence, method="DELETE")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--recovery", action="store_true", help="Stop/recreate services in the selected local Compose project; run only on disposable development stacks")
    args = parser.parse_args()
    ready()
    check_grafana()
    check_examples()
    verify_probe(send_probe())
    if args.recovery:
        recover()
    print("PASS integration verification", flush=True)
