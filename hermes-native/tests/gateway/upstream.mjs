import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { createRequire, registerHooks } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
export const manifest = JSON.parse(readFileSync(resolve(here, 'upstream-lock.json'), 'utf8'));
export const upstreamRoot = process.env.HERMES_UPSTREAM_ROOT;
if (!upstreamRoot) throw new Error('Run through run.mjs with an explicit Hermes checkout.');
for (const entry of manifest.files) {
  const actual = createHash('sha256').update(readFileSync(resolve(upstreamRoot, entry.path))).digest('hex');
  if (actual !== entry.sha256) throw new Error(`Pinned upstream source changed: ${entry.path}`);
}

const channelUrl = pathToFileURL(resolve(upstreamRoot, 'apps/shared/src/json-rpc-channel.ts')).href;
const gatewayUrl = pathToFileURL(resolve(upstreamRoot, 'apps/shared/src/json-rpc-gateway.ts')).href;
// Only this known runtime edge is redirected. Node strips types from original bytes.
registerHooks({
  resolve(specifier, context, nextResolve) {
    if (context.parentURL === gatewayUrl && specifier === './json-rpc-channel.js') {
      return { url: channelUrl, shortCircuit: true };
    }
    return nextResolve(specifier, context);
  },
});
export const channel = await import(channelUrl);
export const gateway = await import(gatewayUrl);
const require = createRequire(pathToFileURL(resolve(upstreamRoot, 'package.json')));
process.env.WS_NO_BUFFER_UTIL = '1';
process.env.WS_NO_UTF_8_VALIDATE = '1';
export const { WebSocketServer } = require(resolve(upstreamRoot, 'node_modules/ws'));
