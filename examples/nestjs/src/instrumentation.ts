import { NodeSDK } from '@opentelemetry/sdk-node';
import { getNodeAutoInstrumentations } from '@opentelemetry/auto-instrumentations-node';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http';

// This module is preloaded before NestJS/HTTP modules are imported.
const sdk = new NodeSDK({
  traceExporter: new OTLPTraceExporter({ timeoutMillis: 2000 }),
  instrumentations: [getNodeAutoInstrumentations({
    '@opentelemetry/instrumentation-fs': { enabled: false },
    '@opentelemetry/instrumentation-http': {
      ignoreIncomingRequestHook: request => ['/metrics', '/health'].includes(request.url?.split('?')[0] ?? ''),
    },
  })],
});
sdk.start();

// Nest handles termination; bound the export flush so shutdown cannot hang.
export async function shutdownTracing(): Promise<void> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  await Promise.race([
    sdk.shutdown(),
    new Promise<void>(resolve => { timer = setTimeout(resolve, 3000); }),
  ]).finally(() => { if (timer) clearTimeout(timer); });
}
