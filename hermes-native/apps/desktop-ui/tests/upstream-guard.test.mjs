import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { execFileSync } from 'node:child_process'
import { assertNoUntrackedSource } from '../scripts/upstream.mjs'

function fixtureRepository(t) {
  const temporaryParent = fs.realpathSync(os.tmpdir())
  const root = fs.mkdtempSync(path.join(temporaryParent, 'hermes-ui-guard-'))
  t.after(() => {
    // Only remove the exact temporary directory this fixture created.
    const actual = fs.realpathSync(root)
    if (path.dirname(actual) !== temporaryParent || !path.basename(actual).startsWith('hermes-ui-guard-')) {
      throw new Error('Refusing cleanup outside the owned fixture directory')
    }
    fs.rmSync(actual, { recursive: true, force: true })
  })
  execFileSync('git', ['-C', root, 'init', '--quiet'], { windowsHide: true, stdio: 'pipe' })
  return root
}

function addFixture(root, relative, contents) {
  const file = path.join(root, relative)
  fs.mkdirSync(path.dirname(file), { recursive: true })
  fs.writeFileSync(file, contents)
}

test('source guard leaves unrelated build caches outside the retained input set', t => {
  const root = fixtureRepository(t)
  addFixture(root, '.cache/result.txt', 'fixture cache')
  assert.doesNotThrow(() => assertNoUntrackedSource(root))
})

test('untracked plugin that would enter the upstream eager glob is rejected', t => {
  const root = fixtureRepository(t)
  addFixture(root, 'apps/desktop/src/plugins/extra/plugin.ts', 'export default {}\n')
  assert.throws(() => assertNoUntrackedSource(root), /untracked source\/asset.*plugins\/extra\/plugin\.ts/)
})

test('gitignored source and assets are also rejected rather than silently bundled', t => {
  const root = fixtureRepository(t)
  addFixture(root, '.gitignore', 'apps/desktop/src/plugins/extra/\napps/desktop/public/local.png\n')
  const plugin = 'apps/desktop/src/plugins/extra/plugin.ts'
  addFixture(root, plugin, 'export default {}\n')
  addFixture(root, 'apps/desktop/public/local.png', 'fixture asset')
  execFileSync('git', ['-C', root, 'check-ignore', '--quiet', plugin], { windowsHide: true, stdio: 'pipe' })
  assert.throws(() => assertNoUntrackedSource(root), /2 untracked source\/asset input/)
})
