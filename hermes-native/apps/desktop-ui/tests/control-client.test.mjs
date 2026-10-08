import test from 'node:test'
import assert from 'node:assert/strict'
import { createControlClient, ControlError } from '../src/control-client.ts'

test('profile writes capture optimistic revision and settings before yielding', async () => {
  const calls = []
  const client = createControlClient({ control: async (operation, payload) => { calls.push({ operation, payload }); return { revision: 2 } } })
  const profile = { context_length: 2048, cache_mode: 'Q4' }
  const pending = client.save('small', 'Small', 1, profile)
  profile.context_length = 8192
  assert.deepEqual(await pending, { revision: 2 })
  assert.deepEqual(calls, [{ operation: 'profiles.save', payload: { profile_id: 'small', name: 'Small', expected_revision: 1, profile: { context_length: 2048, cache_mode: 'Q4' } } }])
})

test('local client exposes no launch, connection or arbitrary request operation', async () => {
  const operations = []
  const client = createControlClient({ control: async operation => { operations.push(operation); return {} } })
  await client.status(); await client.schema(); await client.list(); await client.get('a')
  await client.validate({}); await client.delete('a', 3)
  assert.deepEqual(operations, ['runtime.status', 'profiles.schema', 'profiles.list', 'profiles.get', 'profiles.validate', 'profiles.delete'])
  assert.equal('load' in client, false)
  assert.equal('request' in client, false)
  assert.equal('shutdown' in client, false)
})

test('unavailable and failed local service errors are readable without raw backend text', async () => {
  await assert.rejects(createControlClient().status(), error => error instanceof ControlError && error.code === 'HERMES_CONTROL_UNAVAILABLE')
  const failure = { code: 'REVISION_CONFLICT', message: 'raw sensitive output' }
  const client = createControlClient({ control: async () => { throw failure } })
  await assert.rejects(client.get('a'), error => error.code === 'REVISION_CONFLICT' && !error.message.includes('raw sensitive output'))
  const bad = createControlClient({ control: async () => { throw { get code() { throw new Error('getter') } } } })
  await assert.rejects(bad.status(), { code: 'HERMES_CONTROL_FAILED' })
})
