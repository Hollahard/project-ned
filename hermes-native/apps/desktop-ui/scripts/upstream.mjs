import { createHash } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

export const PINNED_COMMIT = '649d6c0391029f35959cfbc240eb3534a6667cf5'
export const APP_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const INPUTS = ['apps/desktop/src', 'apps/desktop/public', 'apps/desktop/assets', 'apps/desktop/index.html',
  'apps/desktop/vite.config.ts', 'apps/desktop/tsconfig.json', 'apps/desktop/package.json', 'apps/shared', 'package-lock.json']
const GLOB_INPUTS = ['apps/desktop/src', 'apps/desktop/public', 'apps/desktop/assets', 'apps/shared/src']

function git(root, args) {
  return execFileSync('git', ['--no-optional-locks', '-C', root, ...args], {
    encoding: 'utf8', maxBuffer: 8 * 1024 * 1024, windowsHide: true,
    env: { ...process.env, GIT_OPTIONAL_LOCKS: '0' }, stdio: ['ignore', 'pipe', 'pipe']
  })
}

export function assertNoUntrackedSource(root) {
  // Do not use --exclude-standard: ignored plugins/assets can still enter Vite's
  // import.meta.glob/public asset graph and must not masquerade as pinned input.
  const untracked = git(root, ['ls-files', '--others', '-z', '--', ...GLOB_INPUTS]).split('\0').filter(Boolean)
  if (untracked.length) {
    throw new Error(`Retained upstream has ${untracked.length} untracked source/asset input(s): ${untracked.slice(0, 5).join(', ')}. Use a clean pinned checkout.`)
  }
}

export function inspectUpstream() {
  if (!process.env.HERMES_UPSTREAM_ROOT) throw new Error('Set HERMES_UPSTREAM_ROOT to the pinned Hermes source checkout; no default user installation is assumed.')
  const root = fs.realpathSync(process.env.HERMES_UPSTREAM_ROOT)
  const revision = git(root, ['rev-parse', 'HEAD']).trim()
  if (revision !== PINNED_COMMIT) throw new Error(`Expected Hermes ${PINNED_COMMIT}, found ${revision}`)
  assertNoUntrackedSource(root)
  const changed = git(root, ['status', '--porcelain', '--untracked-files=no', '--', ...INPUTS]).trim()
  if (changed) throw new Error('Retained upstream source or lockfile is modified. Use a clean pinned checkout.')
  const files = git(root, ['ls-files', '-z', '--', ...INPUTS]).split('\0').filter(Boolean).sort()
  if (!files.includes('apps/desktop/src/main.tsx') || !files.includes('apps/shared/src/json-rpc-gateway.ts')) {
    throw new Error('Pinned renderer/shared inputs are missing')
  }
  const hash = createHash('sha256')
  for (const relative of files) hash.update(relative).update('\0').update(fs.readFileSync(path.join(root, relative))).update('\0')
  const desktop = path.join(root, 'apps/desktop')
  const manifest = JSON.parse(fs.readFileSync(path.join(desktop, 'package.json'), 'utf8'))
  const dependencies = []
  for (const [name, version] of Object.entries({ ...manifest.dependencies, ...manifest.devDependencies })) {
    if (!/^\d/.test(version)) continue
    const packageFile = [path.join(desktop, 'node_modules', name, 'package.json'), path.join(root, 'node_modules', name, 'package.json')].find(fs.existsSync)
    const actual = packageFile && JSON.parse(fs.readFileSync(packageFile, 'utf8')).version
    if (actual !== version) throw new Error(`Pinned dependency ${name}: expected ${version}, found ${actual ?? 'missing'}. Provision dependencies separately; this wrapper never installs into upstream.`)
    dependencies.push({ name, version })
  }
  return { root, desktop, revision, sourceSha256: hash.digest('hex'), sourceFileCount: files.length, dependencies }
}

export function assertUnchanged(before, after) {
  if (before.revision !== after.revision || before.sourceSha256 !== after.sourceSha256 || before.sourceFileCount !== after.sourceFileCount) {
    throw new Error('Retained upstream inputs changed during verification')
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const result = inspectUpstream()
  console.log(JSON.stringify({ revision: result.revision, sourceSha256: result.sourceSha256,
    sourceFileCount: result.sourceFileCount, pinnedDependencies: result.dependencies.length }, null, 2))
}
