import assert from 'node:assert'
import {
  createNativeGatewaySocketFactory,
  NativeGatewaySocket,
  DEFAULT_SOCKET_LIMITS
} from '../../../hermes-native/apps/desktop-ui/src/native-gateway-socket.ts'

console.log('Testing adversarial cases on native-gateway-socket...')

class MockHost {
  constructor() {
    this.created = []
    this.subscriptions = new Map()
    this.sent = []
    this.acked = []
    this.closed = []
    this.listeners = new Map()
  }
  async create(endpointHandle, signal) {
    const identity = { socketId: endpointHandle, generation: 1 }
    this.created.push(identity)
    return identity
  }
  async subscribe(identity, receive) {
    const key = `${identity.socketId}:${identity.generation}`
    this.listeners.set(key, receive)
    return () => { this.listeners.delete(key) }
  }
  async activate(identity) {}
  async send(identity, sequence, text) {
    this.sent.push({ sequence, text })
    return { sequence, bytesWritten: Buffer.byteLength(text, 'utf8') }
  }
  async ack(identity, sequence) {
    this.acked.push(sequence)
  }
  async close(identity, request) {
    this.closed.push({ identity, request })
    return { ...identity, retired: true }
  }
  emit(identity, event) {
    const key = `${identity.socketId}:${identity.generation}`
    const fn = this.listeners.get(key)
    if (fn) fn(event)
  }
}

// Case 1: Preceding messages dispatched before CloseEvent on remote close
async function testPrecedingMessageOrdering() {
  const host = new MockHost()
  const factory = createNativeGatewaySocketFactory(host)
  const socket = factory('ws://hermes-native.invalid/gateway/test-socket-0001')
  
  const events = []
  socket.onopen = () => events.push('open')
  socket.onmessage = (e) => events.push(`msg:${e.data}`)
  socket.onclose = (e) => events.push(`close:${e.code}`)

  // Wait for activation
  await new Promise(r => setTimeout(r, 20))
  const id = host.created[0]
  assert(id, 'Host create should have been called')

  // Emit open
  host.emit(id, { socketId: id.socketId, generation: id.generation, sequence: 1, kind: 'open' })
  // Emit two messages
  host.emit(id, { socketId: id.socketId, generation: id.generation, sequence: 2, kind: 'message', text: 'first' })
  host.emit(id, { socketId: id.socketId, generation: id.generation, sequence: 3, kind: 'message', text: 'second' })
  // Emit close
  host.emit(id, { socketId: id.socketId, generation: id.generation, sequence: 4, kind: 'close', code: 1000, reason: 'done', wasClean: true })

  // Wait for delivery pump
  await new Promise(r => setTimeout(r, 30))

  assert.deepStrictEqual(events, ['open', 'msg:first', 'msg:second', 'close:1000'],
    `Events should preserve wire order ahead of close: got ${JSON.stringify(events)}`)
  assert.strictEqual(host.acked.length, 3, 'Open and messages should be acked')
  assert.strictEqual(host.closed.length, 1, 'Host close should be called')
  console.log('PASS: testPrecedingMessageOrdering')
}

// Case 2: Peer close does NOT self-certify retirement if host.close hangs; timeout fences factory
async function testPeerCloseNoSelfRetirement() {
  const host = new MockHost()
  let resolveHostClose
  host.close = async (identity, request) => {
    // Hangs host close
    return new Promise(r => { resolveHostClose = r })
  }
  const factory = createNativeGatewaySocketFactory(host, { closeTimeoutMs: 50 })
  const socket = factory('ws://hermes-native.invalid/gateway/test-socket-0002')

  await new Promise(r => setTimeout(r, 20))
  const id = host.created[0]
  host.emit(id, { socketId: id.socketId, generation: id.generation, sequence: 1, kind: 'open' })
  host.emit(id, { socketId: id.socketId, generation: id.generation, sequence: 2, kind: 'close', code: 1000, reason: '', wasClean: true })

  // Wait for closeTimeoutMs to expire and fence the factory
  await new Promise(r => setTimeout(r, 100))

  // Subsequent socket created from fenced factory must be rejected (admitted=false -> immediate fail)
  const rejectedSocket = factory('ws://hermes-native.invalid/gateway/test-socket-0003')
  let errFired = false
  let codeFired = null
  rejectedSocket.onerror = () => { errFired = true }
  rejectedSocket.onclose = (e) => { codeFired = e.code }

  await new Promise(r => setTimeout(r, 20))
  assert.strictEqual(errFired, true, 'Subsequent socket under fenced factory must fire error')
  assert.strictEqual(codeFired, 1006, 'Subsequent socket under fenced factory must close 1006')
  console.log('PASS: testPeerCloseNoSelfRetirement')
}

// Case 3: Out-of-order sequence fails closed immediately
async function testSequenceGapRejection() {
  const host = new MockHost()
  const factory = createNativeGatewaySocketFactory(host)
  const socket = factory('ws://hermes-native.invalid/gateway/test-socket-0004')

  let errorFired = false
  let closeCode = null
  socket.onerror = () => { errorFired = true }
  socket.onclose = (e) => { closeCode = e.code }

  await new Promise(r => setTimeout(r, 20))
  const id = host.created[0]
  // Emit sequence 2 without sequence 1
  host.emit(id, { socketId: id.socketId, generation: id.generation, sequence: 2, kind: 'open' })

  await new Promise(r => setTimeout(r, 20))
  assert.strictEqual(errorFired, true, 'Error must fire on sequence gap')
  assert.strictEqual(closeCode, 1006, 'Socket must close with 1006 on sequence violation')
  console.log('PASS: testSequenceGapRejection')
}

// Case 4: Invalid close code rejects and fails closed
async function testInvalidCloseCodeRejection() {
  const host = new MockHost()
  const factory = createNativeGatewaySocketFactory(host)
  const socket = factory('ws://hermes-native.invalid/gateway/test-socket-0005')

  let errorFired = false
  let closeCode = null
  socket.onerror = () => { errorFired = true }
  socket.onclose = (e) => { closeCode = e.code }

  await new Promise(r => setTimeout(r, 20))
  const id = host.created[0]
  host.emit(id, { socketId: id.socketId, generation: id.generation, sequence: 1, kind: 'open' })
  // RFC 6455: 1005 cannot appear on wire
  host.emit(id, { socketId: id.socketId, generation: id.generation, sequence: 2, kind: 'close', code: 1005, reason: '', wasClean: true })

  await new Promise(r => setTimeout(r, 20))
  assert.strictEqual(errorFired, true, 'Error must fire on reserved close code 1005')
  assert.strictEqual(closeCode, 1006, 'Close code must be 1006 abnormal on invalid wire close')
  console.log('PASS: testInvalidCloseCodeRejection')
}

async function run() {
  await testPrecedingMessageOrdering()
  await testPeerCloseNoSelfRetirement()
  await testSequenceGapRejection()
  await testInvalidCloseCodeRejection()
  console.log('ALL ADVERSARIAL SOCKET TESTS PASSED!')
}

run().catch(err => {
  console.error('FAILED:', err)
  process.exit(1)
})
