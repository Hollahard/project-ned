import { createRequire } from 'node:module'
import { fileURLToPath, pathToFileURL } from 'node:url'
import path from 'node:path'
import fs from 'node:fs'
import { execFileSync } from 'node:child_process'

const root = path.dirname(fileURLToPath(import.meta.url))
if (!process.env.VIRTUAL_ENV) throw new Error('Activate the project virtual environment before this integration check.')
if (!process.env.HERMES_UPSTREAM_ROOT) throw new Error('Set HERMES_UPSTREAM_ROOT to the installed pinned Hermes source checkout.')
const upstream = path.join(fs.realpathSync(process.env.HERMES_UPSTREAM_ROOT), 'apps/desktop')
const native = process.env.HERMES_NATIVE_DESKTOP ? fs.realpathSync(process.env.HERMES_NATIVE_DESKTOP) : path.resolve(root, '../..')
const { inspectUpstream, assertUnchanged } = await import(pathToFileURL(path.join(native, 'scripts/upstream.mjs')).href)
const before = inspectUpstream()
const requireUpstream = createRequire(path.join(upstream, 'package.json'))
const { startVitest } = await import(pathToFileURL(requireUpstream.resolve('vitest/node')).href)
const { default: react } = await import(pathToFileURL(requireUpstream.resolve('@vitejs/plugin-react')).href)
const dependencies = path.dirname(path.dirname(requireUpstream.resolve('vitest/package.json')))
fs.mkdirSync(path.join(root, '.runs'), { recursive: true })
fs.mkdirSync(path.join(root, '.runs/temp'), { recursive: true })
process.env.TEMP = path.join(root, '.runs/temp')
process.env.TMP = process.env.TEMP
process.env.HERMES_UI_TEST_ROOT = root
process.env.HERMES_CONTROL_WORKER_ROOT ??= path.resolve(native, '../../services/control-worker')
process.env.HERMES_INFERENCE_SRC ??= path.resolve(native, '../../services/inference/src')
if (!process.env.HERMES_BASE_PYTHON) {
  const interpreter = path.join(process.env.VIRTUAL_ENV, process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')
  const env = Object.fromEntries(['SystemRoot', 'WINDIR'].filter(key => process.env[key]).map(key => [key, process.env[key]]))
  process.env.HERMES_BASE_PYTHON = execFileSync(interpreter, ['-I', '-S', '-B', '-c', 'import sys; print(sys._base_executable)'], {
    encoding: 'utf8', windowsHide: true, timeout: 5000, maxBuffer: 2048, env,
  }).trim()
}
const context = await startVitest('test', [], {
  config: false, root, watch: false, environment: 'jsdom',
  include: ['settings.test.tsx', 'inspection.test.tsx'], reporters: ['default', 'json'],
  outputFile: { json: path.join(root, '.runs', 'results.json') },
  maxWorkers: 1, fileParallelism: false, testTimeout: 15000,
}, {
  configFile: false, envDir: false, cacheDir: path.join(root, '.cache'),
  plugins: [react()],
  resolve: { alias: [
    { find: '@native', replacement: path.join(native, 'src') },
    { find: '@hermes-native/plugin-context', replacement: path.join(upstream, 'src/contrib/plugin.ts') },
    { find: '@hermes-native/plugin-inventory', replacement: path.join(upstream, 'src/contrib/plugins-store.ts') },
    { find: '@retained', replacement: path.join(upstream, 'src') },
    { find: '@', replacement: path.join(upstream, 'src') },
    { find: /^react-dom(\/.*)?$/, replacement: path.join(dependencies, 'react-dom') + '$1' },
    { find: /^react(\/.*)?$/, replacement: path.join(dependencies, 'react') + '$1' },
    { find: '@testing-library/react', replacement: requireUpstream.resolve('@testing-library/react') },
    { find: 'vitest', replacement: path.join(dependencies, 'vitest/dist/index.js') },
    { find: 'nanostores', replacement: requireUpstream.resolve('nanostores') },
  ] },
})
await context.close()
assertUnchanged(before, inspectUpstream())
