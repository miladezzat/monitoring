# Validation and maintenance

## Checks shipped with the starter

| Command | Evidence | Limitation |
| --- | --- | --- |
| `python3 scripts/check.py` | Compose loopback ports, memory limits and digest locks; deterministic dashboards; pinned Prometheus config/rule tests, Alertmanager config, Loki config and Alloy validation | Tempo configuration is validated by actual startup in the integration suite; syntax checks alone do not prove ingestion |
| `python3 scripts/verify.py` | Backend readiness; provisioned dashboard/data source UIDs and trace link; metrics and SDK traces from both examples; correlated file logs; raw OTLP trace/log storage | Requires the demo profile; HTTP OTLP is exercised, gRPC is configured and parsed but has no end-to-end client probe |
| `python3 scripts/verify.py --recovery` | Both apps respond during backend outage; queued trace/log survives collector SIGKILL; alert fires, reaches Alertmanager and resolves; metrics/logs/traces/dashboard/silence survive full recreation | Short outage with a tiny fixture; no queue saturation, disk failure, load or host-loss guarantee |
| `python3 scripts/verify_backup.py` | Quiesced seven-volume archive, checksums, empty-project restore, existing-data refusal, historical signal/dashboard/silence queries | Single-host local backup, interrupts the source; no cross-version or cloud restore claim |

Alert tests check pending duration/resolution for backend availability, target failures, a sustained high-volume error rate while excluding low-volume noise, queue utilization and file-log drop behavior. The integration suite queries actual storage using unique markers and known trace IDs; a successful exporter response alone is insufficient.

The GitHub workflow runs the full suite on `ubuntu-latest` (amd64) and `ubuntu-24.04-arm` (arm64). It uses an isolated Compose project, a fixed test-only password, pinned checkout action, read-only repository token permissions, failure diagnostics and cleanup. Never use that fixture password for an operated environment.

## Repeat locally

```bash
python3 scripts/setup.py
export COMPOSE_PROJECT_NAME=monitoring-test
python3 scripts/check.py
docker compose --profile demo up -d --build --wait --wait-timeout 180
python3 scripts/verify.py --recovery
python3 scripts/verify_backup.py
# This is destructive only to the selected disposable test project's volumes:
docker compose --profile demo down --volumes --remove-orphans
```

Do not run these commands while another project uses the same host ports. Edit local port overrides or stop that project first. `check.py` uses its own `monitoring-config-check` project and deletes only its temporary volumes. If test runners on the same host run concurrently, give that validation project a separate identity before sharing the host.

## Pinned baseline

The version/digest snapshot was resolved on 2026-10-05. `image-lock.json` contains multi-platform manifest digests, not a claim that these versions remain the newest release.

| Image | Version |
| --- | --- |
| Prometheus | v3.15.0 |
| Alertmanager | v0.34.1 |
| Grafana | 13.2.3 |
| Loki | 3.7.8 |
| Tempo | 3.1.0 |
| Alloy | v1.20.1 |
| Node | 24.16.0-alpine |
| Python | 3.13-alpine, immutable digest records the resolved image |

NestJS/OpenTelemetry/logging/metrics dependencies are exact versions with `package-lock.json`; Docker uses `npm ci`. The Node metrics example uses the maintained [`@prometheus-io/client`](https://github.com/prometheus/client_js). Python's complete dependency set is hash-locked in `requirements.txt`; Docker uses `pip --require-hashes`. `requirements.in` describes the intended direct dependencies. Re-resolve and review transitive changes deliberately, using `uv pip compile --python-version 3.13 --generate-hashes examples/python/requirements.in -o examples/python/requirements.txt` or an equivalent verified locking process.

## Maintenance process

1. Review primary release notes and migrations for every changed backend or instrumentation package.
2. Resolve and inspect manifests for both amd64 and arm64, then update tags and digests together in the lock and every consumer.
3. Rebuild examples from dependency locks; audit dependencies and review logger/SDK behavior changes.
4. Run config/rule checks, ingestion, SIGKILL recovery, recreation and backup/restore. Recheck actual collector metric labels after upgrades.
5. Run the suite against a restored snapshot if changing state formats. Record rollback requirements before replacing any populated environment.
6. Verify CI on both architectures and review the production acceptance gates for the affected environment.

When changing dashboards, edit `scripts/generate_dashboards.py`, run it, and commit both the source and resulting JSON. Stable dashboard/data source UIDs are part of the local integration contract.

The suite does not measure production load, high availability, external alert delivery, real cloud credentials, TLS/SSO policy, exhaustive secret redaction, disk exhaustion, sampling accuracy or gRPC client behavior. Those remain explicit deployment acceptance work rather than implied by green CI.
