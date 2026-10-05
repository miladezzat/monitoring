"""A framework-independent Python example using the same protocol contracts."""
import json
import logging
import os
import queue
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler
from pathlib import Path

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import extract
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

SERVICE = "example-python"
LABELS = {"service_name": SERVICE, "environment": "local"}
REQUESTS = Counter("http_requests_total", "Completed HTTP requests", [*LABELS, "method", "route", "status_code"])
DURATION = Histogram("http_request_duration_seconds", "HTTP request duration", [*LABELS, "method", "route"], buckets=[.005, .01, .05, .1, .25, .5, 1, 2])
DROPPED = Counter("application_log_dropped_total", "Logs dropped by the bounded logger", [*LABELS]).labels(**LABELS)

provider = TracerProvider(resource=Resource.create({"service.name": SERVICE, "deployment.environment.name": "local"}))
provider.add_span_processor(BatchSpanProcessor(
    OTLPSpanExporter(endpoint=os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318").rstrip("/") + "/v1/traces", timeout=2),
    max_queue_size=256, max_export_batch_size=128, schedule_delay_millis=1000,
))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("monitoring.example")


class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({
            **LABELS, "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname.lower(), "message": record.getMessage(),
            "trace_id": record.trace_id, "span_id": record.span_id,
        })


class TraceContext(logging.Filter):
    def filter(self, record):
        context = trace.get_current_span().get_span_context()
        record.trace_id = format(context.trace_id, "032x") if context.is_valid else ""
        record.span_id = format(context.span_id, "016x") if context.is_valid else ""
        return True


class BoundedHandler(QueueHandler):
    def handleError(self, record):
        # A full log queue must not affect the application's response.
        DROPPED.inc()


class BoundedListener(QueueListener):
    def enqueue_sentinel(self):
        self.queue.put(self._sentinel, timeout=2)


class FailOpenFileHandler(RotatingFileHandler):
    def handleError(self, record):
        DROPPED.inc()


console = logging.StreamHandler(sys.stdout)
console.setFormatter(JsonFormatter())
sinks = [console]
try:
    log_path = Path(os.environ.get("LOG_FILE", "./output/python.log"))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = FailOpenFileHandler(log_path, maxBytes=10 * 1024 * 1024, backupCount=2)
    file_handler.setFormatter(JsonFormatter())
    sinks.append(file_handler)
except OSError:
    DROPPED.inc()
handler = BoundedHandler(queue.Queue(maxsize=1024))
handler.addFilter(TraceContext())
logger = logging.getLogger(SERVICE)
logger.setLevel(logging.INFO)
logger.addHandler(handler)
listener = BoundedListener(handler.queue, *sinks)
listener.start()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Do not log raw URLs, headers, or request bodies.

    def respond(self, status, body, content_type="application/json", trace_id=""):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if trace_id:
            self.send_header("X-Trace-Id", trace_id)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/metrics":
            return self.respond(200, generate_latest(), CONTENT_TYPE_LATEST)
        if path == "/health":
            return self.respond(200, b'{"ok":true}')
        route = path if path in ["/", "/slow", "/error"] else "unmatched"
        start = time.monotonic()
        status = 500 if route == "/error" else 404 if route == "unmatched" else 200
        with tracer.start_as_current_span("GET " + route, context=extract(dict(self.headers))) as span:
            span.set_attributes({"http.request.method": "GET", "http.route": route, "http.response.status_code": status})
            if route == "/slow":
                time.sleep(.25)
            if status == 500:
                span.set_status(Status(StatusCode.ERROR, "Example failure"))
                logger.error("example failure")
            else:
                logger.info("hello" if route == "/" else "request " + route)
            self.respond(status, json.dumps({"service": SERVICE, "ok": status == 200}).encode(), trace_id=format(span.get_span_context().trace_id, "032x"))
        REQUESTS.labels(**LABELS, method="GET", route=route, status_code=str(status)).inc()
        DURATION.labels(**LABELS, method="GET", route=route).observe(time.monotonic() - start)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", 8000), Handler)
    server.daemon_threads = True
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: threading.Thread(target=server.shutdown, daemon=True).start())
    try:
        server.serve_forever()
    finally:
        server.server_close()
        provider.shutdown()
        listener.stop()
