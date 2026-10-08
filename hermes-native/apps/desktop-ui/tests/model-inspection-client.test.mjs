import test from 'node:test'
import assert from 'node:assert/strict'
import { createModelInspector } from '../src/model-inspection-client.ts'

test('inspection forwards only the model path, with no root grant or load operation', async () => {
  const calls = []
  const client = createModelInspector({ inspectModel: async path => { calls.push(path); return { status: 'incomplete' } } })
  assert.deepEqual(await client.inspect('C:/granted/model'), { status: 'incomplete' })
  assert.deepEqual(calls, ['C:/granted/model'])
  assert.deepEqual(Object.keys(client), ['inspect'])
})

test('inspection failure messages never echo raw native errors or invoke getters', async () => {
  await assert.rejects(createModelInspector().inspect('C:/model'), { code: 'CATALOG_UNAVAILABLE' })
  for (const failure of [{ code: 'CATALOG_OUTSIDE_GRANT', message: 'sensitive source text' }, { get code() { throw Error('getter') } }]) {
    const client = createModelInspector({ inspectModel: async () => { throw failure } })
    await assert.rejects(client.inspect('C:/model'), error => !error.message.includes('sensitive') && !error.message.includes('getter'))
  }
})
