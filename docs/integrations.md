# Application integration

## Shared contracts

Choose a stable service name such as `billing-api` or `invoice-worker`. Use it as the Prometheus label `service_name`, JSON log field `service_name`, and OpenTelemetry resource attribute `service.name`. The OpenTelemetry resource attribute `deployment.environment.name` identifies the environment; examples use `local`. Loki normalizes OTLP `service.name` into `service_name`.

Propagate W3C `traceparent` and `tracestate` on outbound calls and extract them on inbound requests. A single trace ID can then connect spans across services and connect logs to the request that produced them. The Python example demonstrates extraction; the Node SDK's HTTP instrumentation handles propagation.

Do not use request IDs, user IDs, email addresses, full URLs, or trace IDs as Prometheus labels or Loki indexed labels. Keep trace/span IDs in log bodies or OTLP fields. Use route templates such as `/orders/:id`, fold unmatched routes into `unmatched`, and bound method/status label values. [Prometheus instrumentation practices](https://prometheus.io/docs/practices/instrumentation/) and [Loki label guidance](https://grafana.com/docs/loki/latest/get-started/labels/bp-labels/) explain the cardinality cost.

## Metrics from a host application

Expose `/metrics` in Prometheus text or OpenMetrics format. The endpoint must be reachable from the Prometheus container; a host application listening only on host loopback may need a different local bind address depending on Docker's networking. Keep that development endpoint on a trusted network.

Copy `prometheus/targets/application.json.example` to a `.json` file, or create:

```json
[
  {
    "targets": ["host.docker.internal:8081"],
    "labels": {"service_name": "billing-api", "environment": "local"}
  }
]
```

Docker Desktop resolves the host alias. The Compose `host-gateway` entry supports Linux Docker hosts. This job uses file discovery every 15 seconds; adding or removing a target does not require restarting Prometheus. For a container on the same Compose network, use a service address such as `billing-api:8080`. For another network, connect it deliberately and verify reachability. Avoid storing scrape credentials inside target files; authenticated targets need a separate job with mounted secret files.

The `application` job uses `honor_labels: true`, so labels supplied by a trusted application's endpoint take precedence over discovery labels. Do not reuse this configuration for untrusted tenants. Match target and instrumented service names to keep dashboards and alerts coherent.

Default dashboards expect:

| Metric | Type and labels | Purpose |
| --- | --- | --- |
| `http_requests_total` | Counter: `service_name`, `environment`, `method`, `route`, `status_code` | Request rate, errors, route counts |
| `http_request_duration_seconds` | Histogram: service/environment/method/route, standard `le` buckets | P95 latency |
| `process_resident_memory_bytes` | Gauge | Resident memory |
| `process_cpu_seconds_total` | Counter | CPU cores used |
| `application_log_dropped_total` | Counter with service/environment | Known local logger drops |

Health and metrics requests are excluded from application traffic. The demo histograms use seconds with buckets `0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1, 2`; align buckets when aggregating different services. Framework-specific runtime panels, such as Node heap and event loop lag, require those additional metrics. Workers should expose work counts, durations and queue depth and provide corresponding dashboards; HTTP dashboards will naturally be empty.

Metrics use pull collection here. Sending OTLP metrics to Alloy will not store them in Prometheus because no metrics output is configured. Add and test a separate supported metrics pipeline if that is a requirement.

## Traces from any OpenTelemetry SDK or agent

Use OTLP/HTTP protobuf with a signal-specific endpoint:

```text
OTEL_SERVICE_NAME=billing-api
OTEL_RESOURCE_ATTRIBUTES=deployment.environment.name=local
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://localhost:4318/v1/traces
```

For an application container on the Compose network, replace `localhost` with `alloy`. For OTLP/gRPC, use `alloy:4317` inside the network or `localhost:4317` on the host. Client-specific endpoint schemes and TLS settings vary; follow the selected SDK's documentation. In a container, `localhost` is that container, not the collector.

Load instrumentation before importing application modules. Use asynchronous batch processing with a finite queue, short exporter timeouts and a bounded termination flush. The Node example preloads `dist/instrumentation.js` using `--require`; the Python example creates its provider before starting the server. Exporter failures must not make business requests wait for storage.

| Application runtime | Integration route |
| --- | --- |
| NestJS, Express or another Node service | OpenTelemetry Node SDK/auto instrumentation, a Prometheus client, JSON logger |
| Django, FastAPI or a Python worker | OpenTelemetry Python SDK/instrumentation or manual spans, `prometheus_client`, structured logger |
| Java/Spring | OpenTelemetry Java agent or SDK and a Prometheus-compatible metrics exporter |
| .NET | OpenTelemetry .NET instrumentation and a Prometheus-compatible metrics endpoint |
| Go | OpenTelemetry Go SDK/instrumentation and Prometheus Go client |
| Other runtimes | A supported OTLP exporter or protocol implementation, plus compatible metrics/log output |

These rows describe integration boundaries, not bundled or validated examples for every runtime. Only the NestJS and Python samples are shipped. The raw OTLP probe additionally tests traces/logs without either framework.

Start local tracing with all requests sampled for easy inspection. Set an intentional sampler and test cross-service propagation before production. Scrub sensitive URL query parameters, request attributes and exception content in the application or a collector processor; the local starter does not implement a universal trace redaction policy.

## Logs: choose one route per application

**OTLP route:** use an OpenTelemetry log exporter to Alloy's HTTP `/v1/logs` or gRPC receiver. Include the service resource and trace/span context. To use Grafana's shipped log-to-trace derived field, include `trace_id` in a JSON body, or provision a field mapping appropriate to your log representation. The protocol verification script sends this exact JSON-body format. Context existing only in OTLP structured metadata needs a compatible Grafana mapping; it does not match the shipped body regex automatically.

**File route:** mount the `app-logs` named volume into the application at `/var/log/apps` and write one JSON object per line to an active `*.log` file. Example:

```json
{"service_name":"billing-api","environment":"local","timestamp":"2026-10-05T12:00:00Z","level":"info","message":"invoice processed","trace_id":"0123456789abcdef0123456789abcdef","span_id":"0123456789abcdef"}
```

Alloy extracts `service_name` as a label and applies `environment=local` to the file source; trace IDs remain in the body. The file path label is dropped. The body may contain `timestamp` or the Node logger's `time` field; the configured file pipeline uses collection time as Loki's entry timestamp, retaining the application time in the body. Add and validate a timestamp parsing stage if original event time is required.

The provided examples run as UID 1000 and share that volume. An additional container with a different UID needs a deliberate ownership or group policy; do not make application log folders world-writable as a shortcut. A host application can use OTLP logs, or replace the collector's volume with an explicit read-only bind mount in a local Compose override. Collector access must be restricted to intended files.

Both examples write to stdout and an asynchronous bounded file sink with rotation. Docker also rotates stdout logs, but Alloy does not collect container stdout in this topology. The Node file queue is bounded to 1 MiB; Python's queue is bounded to 1,024 records. File errors and overflow increment a known-drop counter and preserve application responses. These examples demonstrate finite buffering, not audit-grade durable logging. Rotation and file-tail retries can lose records; choose the disk-backed OTLP route or another durable design if stronger delivery is required.

Avoid passwords, tokens, authorization headers, request bodies and personal data in telemetry. The examples emit fixed messages and do not log raw requests; Node also redacts common top-level secret fields. Redaction patterns are not a substitute for reviewing application-specific fields. Limit log record sizes to Loki's 64 KiB line limit.

## Check the integration

1. Find the target in [Prometheus targets](http://localhost:9090/targets), and confirm `up{job="application"}` is `1`.
2. Generate requests, then query `http_requests_total{service_name="billing-api"}`.
3. In Grafana Explore, query `{service_name="billing-api"}` against Loki.
4. Open a known trace ID against Tempo, then follow the log's **Open trace** link.
5. Interrupt the collector in a disposable environment and verify the application still responds. Measure dropped data and recovery under the intended traffic rate.

For local Compose examples and collector health, `python3 scripts/verify.py` performs storage queries using unique markers. It requires the demo profile; custom applications need their own integration checks.
