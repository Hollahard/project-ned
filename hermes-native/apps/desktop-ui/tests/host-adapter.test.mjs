import test from 'node:test'
import assert from 'node:assert/strict'
import { createHostAdapter, CapabilityUnavailableError, HOST_METHODS } from '../src/host-adapter.ts'
import { bootstrapRetainedRenderer } from '../src/bootstrap.ts'

function fixture() {
  const calls = []
  let listener
  let offCalls = 0
  return {
    calls,
    transport: {
      async invoke(command, payload) { calls.push({ command, payload }); return { fixture: true } },
      async subscribe(channel, callback) {
        assert.equal(channel, 'hermes:host:event')
        listener = callback
        return () => { offCalls++ }
      }
    },
    emit: event => listener(event),
    offCalls: () => offCalls
  }
}

test('no native transport cannot manufacture connection, model or version success', async () => {
  const { bridge, binding } = createHostAdapter()
  assert.equal(binding, 'unavailable')
  await assert.rejects(bridge.getConnection('work'), error =>
    error instanceof CapabilityUnavailableError && error.capability === 'getConnection')
  await assert.rejects(bridge.getVersion(), { code: 'HERMES_HOST_CAPABILITY_UNAVAILABLE' })
  assert.throws(() => bridge.onBackendExit(() => {}), CapabilityUnavailableError)
  assert.equal('loadModel' in bridge, false)
  assert.equal('terminal' in bridge, false)
})

test('request captures connection/profile ownership and preserves payload shapes', async () => {
  const f = fixture()
  const { bridge } = createHostAdapter(f.transport)
  const request = { path: '/api/config', method: 'POST', connectionId: 'gateway-a', profile: 'work', body: { enabled: false, item: null } }
  const pending = bridge.api(request)
  request.profile = 'personal'
  request.body.enabled = true
  await pending
  assert.equal(f.calls[0].command, 'hermes_host_request')
  assert.deepEqual(f.calls[0].payload, { method: 'api', args: [{ path: '/api/config', method: 'POST', connectionId: 'gateway-a', profile: 'work', body: { enabled: false, item: null } }] })
})

test('API rejects absolute origins and encoded traversal before native dispatch', () => {
  const f = fixture()
  const { bridge } = createHostAdapter(f.transport)
  for (const path of ['https://example.invalid/api/config', '//host/api/config', '/api/%2e%2e/secret', '/api/a\\b']) {
    assert.throws(() => bridge.api({ path }), TypeError)
  }
  assert.equal(f.calls.length, 0)
})

test('version requests preserve explicit connection/profile scope before yielding', async () => {
  const f = fixture()
  const { bridge } = createHostAdapter(f.transport)
  const scope = { connectionId: 'remote-a', profile: 'work' }
  const pending = bridge.getVersion(scope)
  scope.connectionId = 'remote-b'
  scope.profile = 'personal'
  await pending
  assert.deepEqual(f.calls[0].payload, {
    method: 'getVersion', args: [{ connectionId: 'remote-a', profile: 'work' }]
  })
})

test('multipart buffers and query data survive route capture without rewriting', async () => {
  const f = fixture()
  const adapter = createHostAdapter(f.transport)
  const bytes = new Uint8Array([1, 2, 255])
  await adapter.bridge.api({ path: '/api/fs/read-text?path=../notes', profile: null,
    upload: { filename: 'sample.bin', contentType: 'application/octet-stream', bytes: bytes.buffer } })
  bytes[0] = 8
  const captured = f.calls[0].payload.args[0]
  assert.equal(captured.path, '/api/fs/read-text?path=../notes')
  assert.equal(captured.profile, null)
  assert.deepEqual([...new Uint8Array(captured.upload.bytes)], [1, 2, 255])
})

test('declared methods route explicitly and propagate native errors', async () => {
  const f = fixture()
  const { bridge } = createHostAdapter(f.transport)
  await bridge.getConnectionFor({ connectionId: 'a', profile: 'b' })
  await bridge.getGatewayWsUrlFor({ connectionId: 'a', profile: 'b' })
  await bridge.getGatewayWsUrl('b')
  await bridge.revalidateConnection()
  await bridge.touchBackend('b', { activeTurn: true })
  assert.deepEqual(f.calls.map(c => c.payload.method), ['getConnectionFor', 'getGatewayWsUrlFor', 'getGatewayWsUrl', 'revalidateConnection', 'touchBackend'])
  assert.ok(f.calls.every(c => HOST_METHODS.includes(c.payload.method)))
  const nativeError = Object.assign(new Error('scope denied'), { code: 'DENIED' })
  const denied = createHostAdapter({ ...f.transport, invoke: async () => { throw nativeError } })
  await assert.rejects(denied.bridge.getConnection(), error => error === nativeError)
})

test('startup and recovery methods reject asynchronously with readable native denials', async () => {
  const f = fixture()
  const adapter = createHostAdapter({ ...f.transport, invoke: async (_, { method }) => {
    throw { code: 'HERMES_HOST_CAPABILITY_UNAVAILABLE', capability: method, message: 'ignored raw text' }
  } })
  for (const method of ['getConnection', 'getBootProgress', 'getRecentLogs', 'getBootstrapState', 'resetBootstrap', 'revealLogs']) {
    const pending = adapter.bridge[method]()
    assert.ok(pending instanceof Promise)
    await assert.rejects(pending, error => error instanceof CapabilityUnavailableError
      && error.capability === method && error.message.includes('Managed backend integration is pending.')
      && !error.message.includes('ignored raw text'))
  }
})

test('foreign native errors retain identity without reading error getters', async () => {
  const f = fixture()
  const errors = [
    { code: 'HERMES_HOST_CAPABILITY_UNAVAILABLE', capability: 'another-method' },
    { get code() { throw new Error('must not read getter') } },
    'transport failure', null
  ]
  for (const failure of errors) {
    const adapter = createHostAdapter({ ...f.transport, invoke: async () => { throw failure } })
    await assert.rejects(adapter.bridge.getConnection(), error => error === failure)
  }
})

test('preview subscription receives only preview events and unregisters cleanly', async () => {
  const f = fixture()
  const adapter = createHostAdapter(f.transport)
  const received = []
  const off = adapter.bridge.onPreviewFileChanged(event => received.push(event))
  await adapter.eventSubscriptionReady()
  const payload = { id: 'owned-watch', path: 'C:/fixture/file.txt', url: 'file:///C:/fixture/file.txt' }
  f.emit({ name: 'preview-file-changed', payload })
  f.emit({ name: 'backend-exit', payload: {} })
  off()
  f.emit({ name: 'preview-file-changed', payload })
  assert.deepEqual(received, [payload])
  adapter.dispose()
  assert.equal(f.offCalls(), 1)
})

test('event unsubscribe is scoped and disposal removes native subscription once', async () => {
  const f = fixture()
  const adapter = createHostAdapter(f.transport)
  const events = []
  const off = adapter.bridge.onBackendExit(value => events.push(value))
  adapter.bridge.onPowerResume(() => events.push('resume'))
  await Promise.resolve()
  f.emit({ name: 'backend-exit', payload: { exitCode: 1 } })
  off()
  f.emit({ name: 'backend-exit', payload: { exitCode: 2 } })
  f.emit({ name: 'power-resume', payload: undefined })
  assert.deepEqual(events, [{ exitCode: 1 }, 'resume'])
  adapter.dispose()
  adapter.dispose()
  assert.equal(f.offCalls(), 1)
  await assert.rejects(adapter.bridge.getVersion(), CapabilityUnavailableError)
})

test('dispose during subscription setup releases late native listener', async () => {
  let finish
  let released = 0
  const f = fixture()
  const adapter = createHostAdapter({ ...f.transport, subscribe: () => new Promise(resolve => { finish = resolve }) })
  adapter.bridge.onPowerResume(() => {})
  adapter.dispose()
  finish(() => { released++ })
  await Promise.resolve()
  assert.equal(released, 1)
})

test('repeated old unsubscribe cannot remove a replacement event subscription', async () => {
  const f = fixture()
  const adapter = createHostAdapter(f.transport)
  const offOld = adapter.bridge.onPowerResume(() => {})
  await adapter.eventSubscriptionReady()
  offOld()
  const received = []
  const offNew = adapter.bridge.onPowerResume(() => received.push('new'))
  offOld()
  f.emit({ name: 'power-resume', payload: undefined })
  assert.deepEqual(received, ['new'])
  offNew()
  f.emit({ name: 'power-resume', payload: undefined })
  assert.deepEqual(received, ['new'])
  adapter.dispose()
})

test('native event setup failure is observable and never masquerades as backend exit', async () => {
  const f = fixture()
  const failure = new Error('native subscription rejected')
  const diagnostics = []
  const exits = []
  const adapter = createHostAdapter({ ...f.transport, subscribe: async () => { throw failure } }, error => diagnostics.push(error))
  adapter.bridge.onBackendExit(payload => exits.push(payload))
  await assert.rejects(adapter.eventSubscriptionReady(), error => error === failure)
  assert.deepEqual(diagnostics, [failure])
  assert.deepEqual(exits, [])
  assert.throws(() => adapter.bridge.onPowerResume(() => {}), error => error === failure)
})

test('retained entry evaluates after bridge installation and existing bridge is preserved', async () => {
  const target = {}
  const adapter = await bootstrapRetainedRenderer(target, async () => {
    assert.equal(typeof target.hermesDesktop.getConnection, 'function')
    await assert.rejects(target.hermesDesktop.getConnection(), CapabilityUnavailableError)
  })
  assert.equal(target.hermesDesktop, adapter.bridge)
  await assert.rejects(bootstrapRetainedRenderer(target, async () => {}), /Refusing to replace/)
})

test('failed retained entry disposes the bridge instead of leaving live native resources', async () => {
  const f = fixture()
  const target = { __HERMES_NATIVE_TRANSPORT__: f.transport }
  await assert.rejects(bootstrapRetainedRenderer(target, async () => {
    target.hermesDesktop.onPowerResume(() => {})
    await Promise.resolve()
    throw new Error('retained module initialization failed')
  }), /retained module initialization failed/)
  assert.equal(f.offCalls(), 1)
  await assert.rejects(target.hermesDesktop.getConnection(), CapabilityUnavailableError)
})
