import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const upstream = process.argv[2] ?? process.env.HERMES_UPSTREAM_ROOT;
if (!process.env.VIRTUAL_ENV) {
  console.error('Activate the Project_Ned Python virtual environment before automation.');
  process.exit(2);
}
if (!upstream) {
  console.error('Usage: node hermes-native/tests/gateway/run.mjs <Hermes checkout>');
  process.exit(2);
}
if (Number(process.versions.node.split('.')[0]) < 24) {
  console.error('Node.js 24 or newer is required for built-in TypeScript stripping.');
  process.exit(2);
}
const result = spawnSync(process.execPath, [
  '--test', '--test-concurrency=1', '--test-reporter=spec',
  resolve(here, 'transport.test.mjs'),
], {
  stdio: 'inherit',
  env: {
    ...process.env, HERMES_UPSTREAM_ROOT: resolve(upstream),
    WS_NO_BUFFER_UTIL: '1', WS_NO_UTF_8_VALIDATE: '1',
  },
});
if (result.error) console.error(result.error.message);
process.exit(result.status ?? 1);
