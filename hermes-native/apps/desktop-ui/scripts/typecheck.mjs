import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'
import { spawnSync } from 'node:child_process'
import { APP_ROOT, inspectUpstream } from './upstream.mjs'

const upstream = inspectUpstream()
const checks = path.join(APP_ROOT, '.checks')
fs.mkdirSync(checks, { recursive: true })
const requireUpstream = createRequire(path.join(upstream.desktop, 'package.json'))
const upstreamTsConfig = JSON.parse(fs.readFileSync(path.join(upstream.desktop, 'tsconfig.json'), 'utf8'))
const config = {
  compilerOptions: {
    target: 'ES2023', lib: ['ES2023', 'DOM', 'DOM.Iterable'], module: 'ESNext', moduleResolution: 'Bundler',
    strict: true, noEmit: true, skipLibCheck: true, allowImportingTsExtensions: true,
    resolveJsonModule: true, esModuleInterop: true, jsx: 'react-jsx',
    types: ['node'],
    typeRoots: [path.join(upstream.desktop, 'node_modules/@types'), path.join(upstream.root, 'node_modules/@types')],
    paths: {
      ...Object.fromEntries(Object.entries(upstreamTsConfig.compilerOptions.paths).map(([key, values]) => [key, values.map(value => path.resolve(upstream.desktop, value))])),
      '@hermes/upstream-global': [path.join(upstream.desktop, 'src/global.d.ts')],
      '@/*': [path.join(upstream.desktop, 'src/*')],
      '@hermes/shared': [path.join(upstream.root, 'apps/shared/src/index.ts')],
      '@hermes/shared/*': [path.join(upstream.root, 'apps/shared/src/*')]
    }
  },
  files: [...['host-adapter.ts', 'bootstrap.ts', 'entry.ts', 'virtual.d.ts'].map(file => path.join(APP_ROOT, 'src', file)),
    path.join(upstream.desktop, 'src/vite-env.d.ts')]
}
const configPath = path.join(checks, 'tsconfig.json')
fs.writeFileSync(configPath, JSON.stringify(config, null, 2) + '\n')
const result = spawnSync(process.execPath, [requireUpstream.resolve('typescript/bin/tsc'), '-p', configPath, '--pretty', 'false'],
  { stdio: 'inherit', windowsHide: true, cwd: APP_ROOT })
if (result.error) throw result.error
process.exitCode = result.status ?? 1
