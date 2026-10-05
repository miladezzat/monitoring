# Production deployment path

The shipped Compose configuration is a local, single-host starter. This guide is a deployment plan and acceptance checklist; it does not represent an implemented or load-tested production environment. Choose a topology using measured traffic, retention, availability objectives and the team's operating capacity.

## Stage 1: Establish telemetry contracts locally

Run both examples, then integrate one real service using [the documented contracts](integrations.md). Decide which logs are operational, security/audit or sensitive, and whether each category may be sampled or dropped. Agree on service identity, route cardinality, retention, dashboards, incident ownership and delivery expectations. Keep collectors out of synchronous business request paths.

Evidence to collect: successful ingestion for each signal, a cross-service trace with correlated logs, exporter/collector failure behavior, and label/series growth under realistic requests. Local tests demonstrate the supplied configuration; they do not establish throughput limits.

## Stage 2: Deploy an isolated staging environment

Use separate configuration, credentials, volumes, storage buckets and service identities for each environment. Decide between a managed observability service, a supported self-hosted deployment, or a small single-host setup with an explicitly accepted host failure domain. Do not expose local Compose ports directly to the internet.

For self hosting:

- Put Grafana behind TLS and SSO with an access policy. Rotate the initial admin credential, disable unnecessary local accounts, and manage secrets outside Git.
- Protect OTLP, Loki, Tempo and Prometheus endpoints through private networking and an authenticated TLS gateway or supported service authentication. Enforce tenant identity at a trusted boundary; Loki's local `auth_enabled: false` is unsuitable for an exposed multi-tenant service.
- Restrict network paths: applications to collector; collector to storage; Grafana to query APIs; Prometheus to approved scrape endpoints; Alertmanager to chosen receivers. Restrict outbound destinations and avoid broad cloud permissions.
- Choose supported Loki/Tempo deployment modes and durable object storage where appropriate. Configure lifecycle policies consistently with compaction/retention, encryption and least-privilege bucket access. Use persistent collector storage when required. Distributed Tempo has additional architecture requirements, including Kafka in the current distributed topology; the monolithic local mode does not.
- Move Grafana state to a supported external database if multiple replicas are needed. Choose a supported Prometheus HA/remote storage and Alertmanager HA design if the availability requirement warrants it. Replicas alone do not make the existing filesystem configuration highly available.
- Decide explicitly whether Alloy's preview file-storage component meets the stability policy. Otherwise adopt a supported collector and durable storage extension, then repeat the recovery tests against that path. Persistent queues do not make every upstream buffer durable.

Use current primary documentation for the selected deployment: [Loki installation](https://grafana.com/docs/loki/latest/setup/install/), [Tempo deployment modes](https://grafana.com/docs/tempo/latest/set-up-for-tracing/setup-tempo/plan/deployment-modes/), [Prometheus storage](https://prometheus.io/docs/prometheus/latest/storage/), and [Alloy](https://grafana.com/docs/alloy/latest/). Helm charts, Terraform, remote write, Kubernetes discovery and cloud credentials are not supplied in this repository. Produce those artifacts after the deployment choice is made.

## Stage 3: Measure capacity and failure recovery

Measure each signal independently: requests per second, active metric series and scrape sizes, log bytes/second and active streams, spans/second and average span bytes. Use realistic cardinality, payloads, burst rates and downstream outages. Estimate retained storage from measured ingest volume, compression and index overhead, then verify with observed disk growth. Time retention does not set a disk quota.

Set resource requests/limits, disk quotas, ingestion limits, queue sizes, sampling and retention using these measurements. The local memory limits are not production recommendations. Include SDK queues, collector batches, retry lifetimes and the maximum tolerable loss/replay window in the delivery budget. Monitor queue utilization, rejected/dropped telemetry, backend latency, disk free space, WAL growth and OOM/restart counts. Add host or platform exporters for disk and container metrics; they are not bundled here.

Exercise backend unavailability, collector SIGKILL, queue saturation, disk exhaustion, expired/revoked credentials, network timeout and host loss. Verify both application response behavior and eventual storage contents, including duplicate tolerance. Rehearse rollback after an upgrade and a restore into an empty environment using supported backend backup mechanisms. Local quiesced volume archives are useful for the supplied topology; they are not a replacement for object-store or replicated-service backup plans.

Acceptance evidence includes measured throughput and disk growth, a declared recovery time objective and recovery point objective, tested backups with retention/encryption, and an owner for each failure mode. Set objectives explicitly; this starter does not invent a universal SLA.

## Stage 4: Activate alert delivery and operational ownership

Replace the Alertmanager `local` receiver with the team's approved pager, webhook or other notification route. Supply receiver credentials through the chosen secret mechanism. Test an actual notification, grouping, resolution and silence behavior in staging before relying on it. This repository deliberately configures no external destination.

The shipped rules cover backend scrape failures, custom application target failures, sustained HTTP error rate, exporter queue backlog and collector file-log drops. Thresholds are illustrative development defaults: tune them against service objectives and traffic. HTTP error rate suppresses low-volume services, so it cannot be the only availability signal. Add latency/SLO burn-rate alerts, ingestion rejection/drop alerts and platform capacity alerts where needed.

A Prometheus instance cannot page about its own total outage. Use an independent external availability monitor, an Alertmanager dead-man/watchdog route, or an operated redundant monitoring system. Have that independent path detect host failure as well as query/ingest failure.

Define on-call ownership, upgrade cadence, backup custody, retention review, incident runbooks and access review. Grant query access according to telemetry sensitivity. Validate the independent monitor and notification destination after each deployment.

## Production acceptance gates

| Gate | Required evidence |
| --- | --- |
| Integration | Each supported application emits all required signals with stable identity and working cross-service correlation |
| Access | TLS, SSO or service authentication, network restrictions and secret rotation exercised |
| Data protection | Sensitive fields reviewed, tenant isolation and retention enforced, backups protected |
| Capacity | Representative load, cardinality, disk growth and queue exhaustion measured |
| Reliability | Declared loss/replay boundaries, required stability level, failure and restore drills passed |
| Alerting | Real notification, resolution, silence and independent outage detection verified |
| Release | Exact image/dependency versions, upgrade/rollback rehearsal, ownership and runbooks recorded |

Record the selected production design and evidence in an environment-specific decision record before deployment. Keep the local starter's defaults small and reusable rather than baking one organization's infrastructure into it.
