# Open Source Monitoring Stack

This repository contains a complete configuration template for setting up an open-source monitoring stack using:

- **Prometheus** – Metrics collection
- **Grafana** – Dashboards and visualization
- **Loki** – Log aggregation
- **Promtail** – Log shipping to Loki
- **Tempo** – Distributed tracing
- **NestJS App** – Sample configuration for instrumenting a Node.js/NestJS backend

---

## 📁 Folder Structure

```

monitoring/
├── prometheus/             # Prometheus metrics config
│   └── prometheus.yml
├── grafana/                # Grafana provisioning for datasources
│   └── provisioning/
│       └── datasources/
│           └── datasource.yml
├── loki/                   # Loki log aggregation config
│   └── config.yaml
├── tempo/                  # Tempo tracing config
│   └── tempo-config.yaml
├── promtail/               # Promtail log shipper config
│   └── promtail-config.yaml
└── docker-compose.yml      # Docker Compose setup

````

---

## 🚀 Quick Start

```bash
cd monitoring
docker-compose up -d
````

### Access the Tools

* **Prometheus** – [http://localhost:9090](http://localhost:9090)
* **Grafana** – [http://localhost:3001](http://localhost:3001)

  * Login: `admin / admin`
* **Loki API** – [http://localhost:3100](http://localhost:3100)
* **Tempo** – [http://localhost:3200](http://localhost:3200)

---

## 🔧 How to Use

### 1. 📦 Add Logging in Your NestJS App

Send logs to a folder Promtail watches (e.g., `/var/log/nestjs/app.log`):

```ts
// main.ts
import * as fs from 'fs';
import * as path from 'path';

const logDir = '/var/log/nestjs';
if (!fs.existsSync(logDir)) fs.mkdirSync(logDir, { recursive: true });

const logFile = fs.createWriteStream(path.join(logDir, 'app.log'), { flags: 'a' });
const originalLog = console.log;

console.log = (...args) => {
  originalLog(...args);
  logFile.write(args.join(' ') + '\\n');
};
```

### 2. 📈 Expose Prometheus Metrics in NestJS

Install `prom-client`:

```bash
npm install prom-client
```

Create a service and controller to expose `/metrics` endpoint.

Example:

```ts
@Get('/metrics')
getMetrics(): string {
  return this.metricsService.getMetrics();
}
```

Prometheus will scrape this endpoint every 15s.

---

## 📊 Visualizing in Grafana

### Data Sources

Grafana auto-provisions:

* Prometheus (metrics)
* Loki (logs)
* Tempo (traces)

### Dashboards

1. Open Grafana → "Dashboards" → "New"
2. Add panels for Prometheus metrics (e.g., `http_requests_total`)
3. Use Loki queries like:

   ```logql
   {job="nestjs"}
   ```
4. Add tracing panels via Tempo + Grafana Tempo plugin.

---

## 🛠️ Tips & Troubleshooting

| Problem                            | Solution                                                 |
| ---------------------------------- | -------------------------------------------------------- |
| Logs not appearing in Grafana Logs | Ensure Promtail is mounted to correct host log path      |
| Prometheus can't scrape NestJS     | Use `host.docker.internal:3000` in `prometheus.yml`      |
| Metrics endpoint 404               | Make sure `/metrics` route exists and is not behind auth |
| Grafana not saving dashboards      | Add persistent volume to `/var/lib/grafana` if needed    |

---

## 📜 License

MIT License