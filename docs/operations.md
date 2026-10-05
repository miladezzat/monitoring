# Local operations and recovery

Commands below target the Compose project selected by `COMPOSE_PROJECT_NAME`, default `monitoring`. Export that variable consistently when using a separate project. Host port overrides live in `.env`; concurrent projects also need distinct ports. Backends have no local API authentication, so run them on a trusted development host.

## Startup, readiness and normal shutdown

```bash
docker compose --profile demo up -d --build --wait --wait-timeout 180
python3 scripts/wait.py
docker compose --profile demo ps
docker compose --profile demo logs --tail 100
# Preserve named volumes:
docker compose --profile demo down
```

The readiness sidecar must become healthy. The vendor services are checked through HTTP endpoints by that sidecar; a Compose `running` state alone is not a storage-ingestion check. Demo readiness is checked by the integration script. If a port is occupied, edit its `.env` override before restarting. Existing Grafana users retain their database password when `.env` changes.

## Missing metrics, logs or traces

| Symptom | Check and corrective action |
| --- | --- |
| Application target is down | Prometheus `/targets`: confirm address, network, bind interface, port and `/metrics`; inspect target discovery JSON |
| No application metric panels | Generate traffic, wait for at least two scrapes, confirm contract names and `service_name`; workers need worker-specific panels |
| Demo targets are down with core-only stack | Expected: `demo` targets are configured but optional services are absent; they do not trigger `ApplicationDown` |
| No file logs | Check JSON validity, active `*.log` filename, volume mounted to application and collector, UID permissions and Alloy component health |
| No OTLP logs | Use `/v1/logs` on HTTP port 4318, inspect exporter and collector errors, check resource `service.name` and Loki stream labels |
| No traces | Initialize SDK before application imports, check sampling and `/v1/traces`, distinguish host `localhost` from container `alloy`, query a known trace ID |
| Log-to-trace link missing | The shipped regex expects a lowercase 32-character `trace_id` in a JSON body; adapt provisioning for metadata-only or other formats |
| High collector queues | Inspect Tempo/Loki readiness, backend errors, disk and memory; capacity is finite and retries eventually expire |
| Alert visible but no message delivered | The shipped receiver is local only; configure and verify a real destination for an operated environment |
| Grafana login fails after configuration change | Admin environment values initialize a new database; reset an existing account through the supported Grafana process |

Useful queries:

```promql
up{job="application"}
sum by (service_name) (rate(http_requests_total[5m]))
otelcol_exporter_queue_size{data_type=~"traces|logs"}
otelcol_exporter_queue_size{data_type=~"traces|logs"} / otelcol_exporter_queue_capacity{data_type=~"traces|logs"}
sum(rate(loki_write_dropped_entries_total[5m]))
```

```logql
{service_name="example-python"} | json
{service_name="example-nestjs"} |= "your-trace-id"
```

Do not turn up label cardinality or retry buffers to hide a failing backend. Fix reachability/capacity first, then determine whether any telemetry was dropped. Inspect application drop counters as well as collector metrics. The file route does not have a durable outgoing WAL.

## Backup and restore

Named volumes preserve data across container recreation; they do not protect against deleting volumes or losing the host. The backup helper stops all project containers before archiving all seven data volumes and restarts previously running services afterward. Expect an interruption. It uses the pinned Python image without network access, preserves numeric ownership, creates a new directory with mode `0700`, writes archives with mode `0600`, and records SHA-256 checksums. Backup contents include credentials and sensitive telemetry; keep the directory outside Git and protect copies accordingly.

```bash
# The destination must not exist yet. Use a location outside this checkout:
python3 scripts/backup.py backup "$HOME/monitoring-backups/first-snapshot"
```

Restore into an **empty, stopped** target project, using the same checkout/version and matching Grafana credential. The helper verifies checksums and all target directories before extracting; it refuses to overwrite existing data. The archive format is intended for this topology, not arbitrary untrusted tar files or version migration. If extraction fails midway, discard that recovery project's new volumes and retry into empty ones; restore is not transactional across volumes.

```bash
# Stop the source first if the recovery project will reuse its host ports:
docker compose --profile demo stop
# Select a separate empty target project:
COMPOSE_PROJECT_NAME=monitoring-recovery python3 scripts/backup.py restore "$HOME/monitoring-backups/first-snapshot"
COMPOSE_PROJECT_NAME=monitoring-recovery docker compose --profile demo up -d --build --wait --wait-timeout 180
COMPOSE_PROJECT_NAME=monitoring-recovery python3 scripts/wait.py
```

Check known historical metrics, a log marker and trace ID from before the backup, a user-created Grafana dashboard and Alertmanager silences. The existing database contains the old Grafana password; set the helper environment to that credential when querying it. Stop the recovery project before restarting the source when sharing ports. Do not copy an actively written SQLite database or WAL and assume it is a consistent backup.

`python3 scripts/verify_backup.py` automates a disposable round trip: create known telemetry/dashboard/silence, quiesce and archive the source, restore all volumes into a random new project, reject a second overwrite attempt, query the original state, delete only the temporary recovery project/archives, and resume the source. It requires the demo profile and prior example traffic. It interrupts the source, so use it only in a disposable environment.

## Retention and disk pressure

Monitor free space on the Docker data disk. Loki and Tempo retention deletion is asynchronous; Prometheus retention size excludes some transient/WAL overhead. Queues and local filesystem data have no enforced byte quota here. Application log rotation and Docker log-driver rotation are separate. Add platform/host storage monitoring for an operated system.

Avoid deleting WAL or queue files while services are running. Under pressure, stop ingestion, preserve a recovery copy where feasible, and adjust capacity or retention using supported backend procedures. Queue deletion loses pending telemetry; deleting a data volume loses the corresponding stored signal or user state.

## Upgrade and rollback

Back up and rehearse restoring before changing backend versions, schema or durable-queue formats. Change version and digest together in `image-lock.json`, Compose and Dockerfiles; rebuild dependency locks when upgrading examples. Run the complete validation suite on an empty project and a restored copy of existing data. Keep the old source/version with its backup.

Rolling back an image against a database or queue written by a newer version may be unsupported. Restore the pre-upgrade snapshot with the matching old configuration when required. Do not change Loki's existing schema start dates or remove old schema entries for populated storage without a documented migration.
