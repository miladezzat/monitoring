import 'reflect-metadata';
import { Controller, Get, HttpException, Module, LoggerService } from '@nestjs/common';
import { NestFactory } from '@nestjs/core';
import { context, trace } from '@opentelemetry/api';
import { collectDefaultMetrics, Counter, Histogram, Registry } from '@prometheus-io/client';
import pino from 'pino';
import { createWriteStream, mkdirSync, renameSync, existsSync, statSync, WriteStream } from 'node:fs';
import { dirname } from 'node:path';
import { Writable } from 'node:stream';
import { shutdownTracing } from './instrumentation';

const serviceName = process.env.OTEL_SERVICE_NAME ?? 'example-nestjs';
const registry = new Registry();
registry.setDefaultLabels({ service_name: serviceName, environment: 'local' });
collectDefaultMetrics({ register: registry });
const requests = new Counter({ name: 'http_requests_total', help: 'Completed HTTP requests', labelNames: ['method', 'route', 'status_code'], registers: [registry] });
const duration = new Histogram({ name: 'http_request_duration_seconds', help: 'HTTP request duration', labelNames: ['method', 'route'], buckets: [0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1, 2], registers: [registry] });
const droppedLogs = new Counter({ name: 'application_log_dropped_total', help: 'Logs dropped by the bounded local file writer', registers: [registry] });

// An asynchronous file sink with bounded buffering and size-based rotation.
// stdout remains available when the local disk is unavailable.
const logPath = process.env.LOG_FILE ?? './output/nestjs.log';
let file: WriteStream | undefined;
let fileFailed = false;
let bytes = 0;
const handleFileError = () => { fileFailed = true; };
try {
  mkdirSync(dirname(logPath), { recursive: true });
  bytes = existsSync(logPath) ? statSync(logPath).size : 0;
  file = createWriteStream(logPath, { flags: 'a' });
  file.on('error', handleFileError);
} catch { fileFailed = true; }
const sink = new Writable({
  write(chunk: Buffer, _encoding, done) {
    if (!file || fileFailed || file.writableLength + chunk.length > 1024 * 1024) {
      droppedLogs.inc();
    } else {
      file.write(chunk, error => { if (error) droppedLogs.inc(); });
      bytes += chunk.length;
      if (bytes >= 10 * 1024 * 1024) {
        file.end();
        try {
          if (existsSync(logPath + '.1')) renameSync(logPath + '.1', logPath + '.2');
          renameSync(logPath, logPath + '.1');
          file = createWriteStream(logPath, { flags: 'a' });
          file.on('error', handleFileError);
          bytes = 0;
        } catch { fileFailed = true; }
      }
    }
    done();
  },
});
const logger = pino({
  base: { service_name: serviceName, environment: 'local' },
  timestamp: pino.stdTimeFunctions.isoTime,
  redact: ['authorization', 'password', 'token'],
  mixin() {
    const span = trace.getSpan(context.active())?.spanContext();
    return span ? { trace_id: span.traceId, span_id: span.spanId } : {};
  },
}, pino.multistream([{ stream: process.stdout }, { stream: sink }]));

class AppLogger implements LoggerService {
  log(message: unknown) { logger.info({ message }); }
  error(message: unknown) { logger.error({ message }); }
  warn(message: unknown) { logger.warn({ message }); }
  debug(message: unknown) { logger.debug({ message }); }
  verbose(message: unknown) { logger.trace({ message }); }
}

@Controller()
class AppController {
  @Get('/') index() { logger.info({ message: 'hello' }); return { service: serviceName, ok: true }; }
  @Get('/slow') async slow() { await new Promise(resolve => setTimeout(resolve, 250)); logger.info({ message: 'slow request' }); return { ok: true }; }
  @Get('/error') error() { logger.error({ message: 'example failure' }); throw new HttpException('Example failure', 500); }
  @Get('/health') health() { return { ok: true }; }
  @Get('/metrics') async metrics() { return registry.metrics(); }
}

@Module({ controllers: [AppController] })
class AppModule {}

async function main() {
  const app = await NestFactory.create(AppModule, { logger: new AppLogger() });
  app.use((req: any, res: any, next: () => void) => {
    const path = req.path;
    const spanContext = trace.getSpan(context.active())?.spanContext();
    if (spanContext) res.setHeader('X-Trace-Id', spanContext.traceId);
    if (path === '/metrics') res.setHeader('Content-Type', registry.contentType);
    if (!['/metrics', '/health'].includes(path)) {
      // Unmatched URLs and methods are folded into bounded label values.
      const route = ['/', '/slow', '/error'].includes(path) ? path : 'unmatched';
      const method = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'].includes(req.method) ? req.method : 'OTHER';
      const start = process.hrtime.bigint();
      res.on('finish', () => {
        requests.inc({ method, route, status_code: String(res.statusCode) });
        duration.observe({ method, route }, Number(process.hrtime.bigint() - start) / 1e9);
      });
    }
    next();
  });
  await app.listen(3000, '0.0.0.0');
  for (const signal of ['SIGTERM', 'SIGINT'] as const) {
    process.once(signal, async () => {
      await app.close();
      await shutdownTracing().catch(() => {});
      if (file && !fileFailed) {
        await Promise.race([
          new Promise<void>(resolve => file!.end(resolve)),
          new Promise<void>(resolve => { const timer = setTimeout(resolve, 2000); timer.unref(); }),
        ]);
      }
      process.exit(0);
    });
  }
}
void main();
