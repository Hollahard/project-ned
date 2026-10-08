import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'
import { APP_ROOT, inspectUpstream, assertUnchanged } from './upstream.mjs'

const before = inspectUpstream()
// Babel resolves its React Compiler preset relative to process.cwd(). Match
// upstream's normal build directory without writing there.
process.chdir(before.desktop)
const requireUpstream = createRequire(path.join(before.desktop, 'package.json'))
const { build, mergeConfig } = await import(pathToFileURL(requireUpstream.resolve('vite')).href)
// Native Node 24 TypeScript loading avoids Vite's bundled-config cache under
// upstream node_modules/.vite-temp. No upstream source/config is rewritten.
const upstreamModule = await import(pathToFileURL(path.join(before.desktop, 'vite.config.ts')).href)
const upstreamConfig = typeof upstreamModule.default === 'function'
  ? await upstreamModule.default({ command: 'build', mode: 'production', isSsrBuild: false, isPreview: false })
  : upstreamModule.default
const outDir = path.join(APP_ROOT, 'dist')
const cacheDir = path.join(APP_ROOT, '.cache')
const entry = path.join(APP_ROOT, 'src/entry.ts').replaceAll('\\', '/')
let entryReplaced = false
const wrapperPlugin = {
  name: 'hermes-native:retained-entry-wrapper',
  enforce: 'pre',
  transformIndexHtml: {
    order: 'pre',
    handler(html) {
      if (!html.includes('src="/src/main.tsx"')) throw new Error('Pinned upstream HTML entry shape changed')
      entryReplaced = true
      return html.replace('src="/src/main.tsx"', 'src="/@hermes-native/bootstrap.ts"')
    }
  },
  resolveId(id) { if (id === '/@hermes-native/bootstrap.ts') return entry }
}
const config = mergeConfig(upstreamConfig, {
  configFile: false,
  root: before.desktop,
  envDir: false,
  cacheDir,
  logLevel: 'warn',
  plugins: [wrapperPlugin],
  resolve: { alias: {
    '@hermes-native/retained-entry': path.join(before.desktop, 'src/main.tsx'),
    '@hermes-native/plugin-context': path.join(before.desktop, 'src/contrib/plugin.ts'),
    '@hermes-native/plugin-inventory': path.join(before.desktop, 'src/contrib/plugins-store.ts')
  } },
  build: { outDir, emptyOutDir: true, reportCompressedSize: false }
})
try {
  await build(config)
  if (!entryReplaced) throw new Error('The retained renderer was not wrapped')
} finally {
  assertUnchanged(before, inspectUpstream())
}
const report = {
  status: 'production-bundle-only',
  revision: before.revision,
  sourceSha256: before.sourceSha256,
  retainedSourceFiles: before.sourceFileCount,
  verifiedPinnedDirectDependencies: before.dependencies,
  upstreamConfig: 'loaded unchanged; React resolution, React Compiler, Tailwind, assets and chunk policy retained',
  overrides: ['bootstrap entry', 'output/cache directory', 'disable dotenv reads', 'quiet build logging'],
  upstreamInputsUnchanged: true,
  runtimeStarted: false,
  nativeHostBinding: 'not exercised by this bundle command; verify sibling desktop-shell',
  visualParity: 'not tested',
  modelOrGpuOperation: false
}
fs.writeFileSync(path.join(outDir, 'feasibility-report.json'), JSON.stringify(report, null, 2) + '\n')
console.log(JSON.stringify({ status: report.status, sourceSha256: report.sourceSha256,
  retainedSourceFiles: report.retainedSourceFiles, upstreamInputsUnchanged: true, outDir }, null, 2))
