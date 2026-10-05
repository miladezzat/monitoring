# Monitoring starter

A reusable, framework-independent observability starter for local development, with a documented production deployment path. Applications integrate through **Prometheus metrics**, **structured JSON or OTLP logs**, and **OpenTelemetry traces**. NestJS and Python are runnable examples of the same contracts; the monitoring stack has no framework dependency.

The local stack includes Prometheus, Grafana, Loki, Tempo, Grafana Alloy, and Alertmanager. It provisions application, runtime, and pipeline dashboards with log-to-trace links. Images are pinned by version and multi-platform digest, credentials are generated locally, published ports bind to loopback, and state survives container recreation.

## Quick start

Prerequisites: Docker Engine or Docker Desktop with Compose v2 supporting `--wait`, Python 3.12+, and an available internet connection for the first image pull/build. Allocate at least 4 GiB to Docker for this small demo; more headroom helps dependency builds. The CI matrix exercises Linux amd64 and arm64.

```bash
git clone https://github.com/miladezzat/monitoring.git
cd monitoring
python3 scripts/setup.py
# Core stack only:
docker compose up -d --wait --wait-timeout 180
# Or core stack plus both runnable examples:
docker compose --profile demo up -d --build --wait --wait-timeout 180
python3 scripts/wait.py
```

Open [Grafana](http://localhost:3001). Sign in with `GRAFANA_ADMIN_USER` and the random `GRAFANA_ADMIN_PASSWORD` in your local `.env`. Setup creates this ignored file with mode `0600` and refuses to overwrite it. Edit `.env` to change host ports, then recreate containers. Grafana's initial admin password is stored in its database; changing the environment variable does not reset an existing account.

Generate example traffic:

```bash
curl http://localhost:3000/
curl http://localhost:3000/slow
curl http://localhost:3000/error
curl http://localhost:3002/
python3 scripts/verify.py
```

`/error` deliberately returns HTTP 500. Open the **Monitoring** dashboard folder: application traffic and logs, application runtime, and monitoring pipeline health. Click **Open trace** on a JSON log with a `trace_id`. Rate panels need multiple scrapes; the interval is 15 seconds. Node-only runtime panels will be empty for other languages unless equivalent metrics are provided.

| Local endpoint | Purpose |
| --- | --- |
| [Grafana :3001](http://localhost:3001) | Dashboards and Explore |
| [Prometheus :9090](http://localhost:9090) | Metrics, targets, alert rules |
| [Loki :3100](http://localhost:3100/ready) | Log API and readiness |
| [Tempo :3200](http://localhost:3200/ready) | Trace API and readiness |
| [Alloy :12345](http://localhost:12345) | Collector health and component graph |
| `localhost:4317`, `localhost:4318` | OTLP gRPC / HTTP **logs and traces** |
| [Alertmanager :9093](http://localhost:9093) | Active alerts and silences |
| [NestJS :3000](http://localhost:3000), [Python :3002](http://localhost:3002) | Optional demo applications |

## Integrate any application

1. Expose a Prometheus-compatible metrics endpoint and add a target in `prometheus/targets/*.json`.
2. Send traces to Alloy using an OpenTelemetry SDK or agent. Send logs using OTLP or the shared JSON file path, choosing one route per application.
3. Use a stable service name across all signals and propagate W3C trace context.

Start with [integration recipes and telemetry contracts](docs/integrations.md). They cover host applications, Compose services, other runtimes, labels, privacy, and metric naming. OTLP metrics, infrastructure exporters, Kubernetes manifests, and hosted deployment automation are extension points, outside the implemented local stack.

## Validate and operate

```bash
# Syntax, image locks, dashboard generation, and Prometheus rule behavior:
python3 scripts/check.py
# Real ingestion from both demos and a raw OTLP protocol probe:
python3 scripts/verify.py
# Disposable demo stacks only: backend outage, SIGKILL, alerting and recreation:
python3 scripts/verify.py --recovery
# Disposable demo stacks only: quiesced backup and empty-project restore drill:
python3 scripts/verify_backup.py
# Stop without deleting stored telemetry:
docker compose --profile demo down
```

The two fault drills interrupt **only the selected Compose project**, with `COMPOSE_PROJECT_NAME` defaulting to `monitoring`. Use a disposable local project. Do not run them against a shared or production deployment. `down --volumes` deletes telemetry, dashboards, silences, and queues; ordinary `down` preserves them.

The OTLP export queues persist to disk using Alloy's **public-preview** file storage component at the pinned version. The restart test verifies this configured path under a short outage, not unlimited or lossless delivery. File log forwarding has bounded retries and can lose entries during an outage or rotation. Alertmanager's local receiver displays alerts without sending external notifications.

- [Architecture and decision records](docs/architecture.md)
- [Production path and acceptance gates](docs/production.md)
- [Troubleshooting, backup and restore](docs/operations.md)
- [Validation and version upgrades](docs/testing.md)

This Compose topology is a single-host development starter. Production requires separate credentials, authenticated network access, durable storage, capacity planning, real notification routing, and an independent availability monitor. The [production guide](docs/production.md) makes those requirements explicit.

## Repository layout

```text
alloy/                  Collection, batching, retry queues, JSON file tailing
prometheus/             Scrape configuration, target discovery, alert rules
alertmanager/           Local alert routing
loki/                   TSDB v13 log storage and retention
tempo/                  Monolithic trace storage and retention
grafana/                Provisioned data sources and generated dashboards
examples/nestjs/        Preloaded OpenTelemetry, Prometheus metrics, JSON logs
examples/python/        Standard-library HTTP server with the same contracts
scripts/                Setup, validation, ingestion, fault and backup drills
tests/                  Alert behavior tests run by promtool
docs/                   Architecture, integration and operations guidance
image-lock.json         Manifest digests used by Compose and example images
```

Licensed under [MIT](LICENSE).
