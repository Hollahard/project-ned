/** Standalone text-only gateway adapter. No browser dial or production bridge. */
export interface SocketIdentity { socketId: string; generation: number }
export type SocketEvent = SocketIdentity & { sequence: number } & (
  | { kind: 'open' }
  | { kind: 'message'; text: string }
  | { kind: 'error' }
  | { kind: 'close'; code: number; reason: string; wasClean: boolean }
)
export interface SocketHost {
  create(endpointHandle: string, signal: AbortSignal): Promise<SocketIdentity>
  subscribe(identity: SocketIdentity, receive: (event: unknown) => void): Promise<() => void>
  activate(identity: SocketIdentity): Promise<void>
  /** Fulfillment means these bytes were written, not merely queued. */
  send(identity: SocketIdentity, sequence: number, text: string): Promise<{ sequence: number; bytesWritten: number }>
  ack(identity: SocketIdentity, sequence: number): Promise<void>
  /** Fulfillment certifies socket actor retirement; never backend/Job cleanup. */
  close(identity: SocketIdentity, request: { code?: number; reason?: string; abort: boolean }): Promise<SocketIdentity & { retired: true }>
}
export interface SocketLimits {
  maxSockets: number; maxMessageBytes: number; maxQueuedMessages: number; maxQueuedBytes: number
  maxIncomingMessages: number; maxIncomingBytes: number; operationTimeoutMs: number; closeTimeoutMs: number
}
export const DEFAULT_SOCKET_LIMITS: Readonly<SocketLimits> = Object.freeze({
  maxSockets: 8, maxMessageBytes: 1_048_576, maxQueuedMessages: 64, maxQueuedBytes: 4_194_304,
  maxIncomingMessages: 128, maxIncomingBytes: 8_388_608, operationTimeoutMs: 15_000, closeTimeoutMs: 2_000,
})
const encoder = new TextEncoder()
const decoder = new TextDecoder()
const endpointPattern = /^ws:\/\/hermes-native\.invalid\/gateway\/([A-Za-z0-9_-]{16,128})$/
const record = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value)
const exact = (value: Record<string, unknown>, keys: string[]) => Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key))
const positive = (value: unknown): value is number => Number.isSafeInteger(value) && (value as number) > 0
const identity = (value: unknown): value is SocketIdentity => record(value) && exact(value, ['socketId', 'generation']) && typeof value.socketId === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(value.socketId) && positive(value.generation)
const same = (a: SocketIdentity, b: SocketIdentity) => a.socketId === b.socketId && a.generation === b.generation

/** Counts the USVString UTF-8 bytes without allocating an attacker-sized copy. */
function bytes(text: string): number {
  let size = 0
  for (let i = 0; i < text.length; i++) {
    const code = text.charCodeAt(i)
    if (code < 0x80) size++
    else if (code < 0x800) size += 2
    else if (code >= 0xd800 && code <= 0xdbff && i + 1 < text.length && text.charCodeAt(i + 1) >= 0xdc00 && text.charCodeAt(i + 1) <= 0xdfff) { size += 4; i++ }
    else size += 3
  }
  return size
}
class SocketCloseEvent extends Event implements CloseEvent {
  readonly code: number; readonly reason: string; readonly wasClean: boolean
  constructor(code: number, reason: string, wasClean: boolean) { super('close'); this.code = code; this.reason = reason; this.wasClean = wasClean }
}

export interface NativeSocketFactory { (url: string): NativeGatewaySocket; dispose(): void }

export function createNativeGatewaySocketFactory(host: SocketHost, overrides: Partial<SocketLimits> = {}): NativeSocketFactory {
  const limits = Object.freeze({ ...DEFAULT_SOCKET_LIMITS, ...overrides })
  for (const key of Object.keys(limits) as (keyof SocketLimits)[]) {
    if (!positive(limits[key]) || limits[key] > DEFAULT_SOCKET_LIMITS[key]) throw new RangeError('Invalid native socket limit')
  }
  const sockets = new Set<NativeGatewaySocket>()
  let fenced = false
  const factory = ((url: string) => {
    const admitted = !fenced && sockets.size < limits.maxSockets
    const socket = new NativeGatewaySocket(host, url, limits, admitted, () => { fenced = true }, value => sockets.delete(value))
    if (admitted) sockets.add(socket)
    return socket
  }) as NativeSocketFactory
  factory.dispose = () => { fenced = true; for (const socket of sockets) socket.dispose() }
  return factory
}

/** Structurally exposes WebSocket, but binary send is deliberately unsupported. */
export class NativeGatewaySocket extends EventTarget implements WebSocket {
  readonly CONNECTING = 0; readonly OPEN = 1; readonly CLOSING = 2; readonly CLOSED = 3
  readonly url: string; readonly protocol = ''; readonly extensions = ''
  binaryType: BinaryType = 'blob'
  #state: 0 | 1 | 2 | 3 = 0
  #buffered = 0
  #identity: SocketIdentity | null = null
  #abort = new AbortController()
  #unsubscribe: (() => void) | null = null
  #terminal = false; #errorSent = false; #nativeRetired = false; #closingHost = false; #activationStarted = false
  #pending = 0; #receiveSequence = 0; #sendSequence = 0
  #queue: { sequence: number; text: string; bytes: number }[] = []
  #queuedCount = 0; #queuedBytes = 0; #sending = false
  #incoming: { event: SocketEvent; bytes: number }[] = []
  #incomingBytes = 0; #incomingCount = 0; #receiving = false
  #remoteClose: Extract<SocketEvent, { kind: 'close' }> | null = null
  #closeRequest: { code?: number; reason?: string; abort: boolean } = { abort: false }
  #closeTimer: ReturnType<typeof setTimeout> | undefined
  #handlers: Partial<{ [K in keyof WebSocketEventMap]: (this: WebSocket, event: WebSocketEventMap[K]) => unknown }> = {}
  #handlerInstalled = new Map<keyof WebSocketEventMap, EventListener>()
  #host: SocketHost; #limits: Readonly<SocketLimits>; #fence: () => void; #release: (socket: NativeGatewaySocket) => void

  constructor(host: SocketHost, url: string, limits: Readonly<SocketLimits>, admitted: boolean, fence: () => void, release: (socket: NativeGatewaySocket) => void) {
    super(); this.#host = host; this.url = typeof url === 'string' ? url : ''; this.#limits = limits; this.#fence = fence; this.#release = release
    // Even synchronous transport throws must happen after callers can subscribe.
    queueMicrotask(() => { if (!admitted || !endpointPattern.test(this.url)) { this.#nativeRetired = true; this.#fail(); return }; void this.#start() })
  }
  get readyState(): 0 | 1 | 2 | 3 { return this.#state }
  get bufferedAmount(): number { return this.#buffered }
  get onopen() { return this.#handlers.open ?? null }
  set onopen(value: ((this: WebSocket, event: Event) => unknown) | null) { this.#handler('open', value) }
  get onerror() { return this.#handlers.error ?? null }
  set onerror(value: ((this: WebSocket, event: Event) => unknown) | null) { this.#handler('error', value) }
  get onmessage() { return this.#handlers.message ?? null }
  set onmessage(value: ((this: WebSocket, event: MessageEvent) => unknown) | null) { this.#handler('message', value) }
  get onclose() { return this.#handlers.close ?? null }
  set onclose(value: ((this: WebSocket, event: CloseEvent) => unknown) | null) { this.#handler('close', value) }
  #handler<K extends keyof WebSocketEventMap>(kind: K, value: ((this: WebSocket, event: WebSocketEventMap[K]) => unknown) | null) {
    if (value === null) {
      delete this.#handlers[kind]
      const previous = this.#handlerInstalled.get(kind)
      if (previous) super.removeEventListener(kind, previous)
      this.#handlerInstalled.delete(kind)
      return
    }
    Object.assign(this.#handlers, { [kind]: value })
    if (!this.#handlerInstalled.has(kind)) {
      const listener = (event: Event) => this.#handlers[kind]?.call(this, event as WebSocketEventMap[K])
      this.#handlerInstalled.set(kind, listener)
      super.addEventListener(kind, listener)
    }
  }
  override addEventListener<K extends keyof WebSocketEventMap>(type: K, listener: (this: WebSocket, ev: WebSocketEventMap[K]) => unknown, options?: boolean | AddEventListenerOptions): void
  override addEventListener(type: string, listener: EventListenerOrEventListenerObject | null, options?: boolean | AddEventListenerOptions): void
  override addEventListener(type: string, listener: EventListenerOrEventListenerObject | null, options?: boolean | AddEventListenerOptions): void { super.addEventListener(type, listener, options) }
  override removeEventListener<K extends keyof WebSocketEventMap>(type: K, listener: (this: WebSocket, ev: WebSocketEventMap[K]) => unknown, options?: boolean | EventListenerOptions): void
  override removeEventListener(type: string, listener: EventListenerOrEventListenerObject | null, options?: boolean | EventListenerOptions): void
  override removeEventListener(type: string, listener: EventListenerOrEventListenerObject | null, options?: boolean | EventListenerOptions): void { super.removeEventListener(type, listener, options) }

  #call<T>(operation: () => Promise<T>, timeout = this.#limits.operationTimeoutMs): Promise<T> {
    this.#pending++
    const raw = Promise.resolve().then(operation)
    void raw.then(() => { this.#pending--; this.#maybeRelease() }, () => { this.#pending--; this.#maybeRelease() })
    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => { this.#fence(); reject(new Error('Native socket operation expired')) }, timeout)
      raw.then(value => { clearTimeout(timer); resolve(value) }, () => { clearTimeout(timer); reject(new Error('Native socket operation failed')) })
    })
  }
  async #start() {
    if (this.#terminal) return
    if (this.#state !== this.CONNECTING) { this.#nativeRetired = true; this.#fail(); return }
    try {
      const opened = await this.#call(async () => {
        const result = await this.#host.create(endpointPattern.exec(this.url)![1], this.#abort.signal)
        if (!identity(result)) { this.#fence(); throw new Error('Invalid native identity') }
        this.#identity = Object.freeze({ ...result })
        if (this.#terminal || this.readyState === this.CLOSING) void this.#retireHost(true)
        return result
      })
      if (this.#terminal || this.readyState === this.CLOSING) { void this.#retireHost(true); return }
      await this.#call(async () => {
        const unsubscribe = await this.#host.subscribe(opened, event => this.#receive(event))
        if (typeof unsubscribe !== 'function') { this.#fence(); throw new Error('Invalid subscription') }
        if (this.#terminal) { unsubscribe(); return }
        this.#unsubscribe = unsubscribe
      })
      if (!this.#terminal && this.readyState === this.CONNECTING) {
        this.#activationStarted = true
        await this.#call(() => this.#host.activate(opened))
      }
    } catch { if (!this.#identity) this.#fence(); this.#fail() }
  }
  send(data: string | Blob | BufferSource): void {
    if (this.#state === this.CONNECTING) throw new DOMException('Socket is connecting', 'InvalidStateError')
    if (typeof data !== 'string') throw new TypeError('Native gateway accepts text only')
    const size = bytes(data)
    this.#buffered = Math.min(Number.MAX_SAFE_INTEGER, this.#buffered + size)
    if (this.#state !== this.OPEN) return // Browser text send discards after close.
    if (size > this.#limits.maxMessageBytes || this.#queuedCount >= this.#limits.maxQueuedMessages || this.#queuedBytes + size > this.#limits.maxQueuedBytes) {
      this.#state = this.CLOSING; queueMicrotask(() => this.#fail()); return
    }
    this.#queuedCount++; this.#queuedBytes += size
    this.#queue.push({ sequence: ++this.#sendSequence, text: decoder.decode(encoder.encode(data)), bytes: size })
    void this.#pumpSend()
  }
  async #pumpSend() {
    if (this.#sending || this.#terminal) return
    this.#sending = true
    try {
      while (this.#queue.length && !this.#terminal) {
        const item = this.#queue.shift()!
        const result = await this.#call(() => this.#host.send(this.#identity!, item.sequence, item.text))
        if (!record(result) || !exact(result, ['sequence', 'bytesWritten']) || result.sequence !== item.sequence || result.bytesWritten !== item.bytes) throw new Error('Invalid write receipt')
        this.#buffered = Math.max(0, this.#buffered - item.bytes)
        this.#queuedCount--; this.#queuedBytes -= item.bytes
      }
    } catch { this.#fail() }
    finally { this.#sending = false; if (this.#state === this.CLOSING && !this.#terminal) void this.#retireHost(false) }
  }
  #receive(value: unknown) {
    if (this.#terminal) return
    if (!record(value) || !this.#identity) { this.#fail(); return }
    // A shared event bus may deliver another socket/generation; never grant it authority.
    if (value.socketId !== this.#identity.socketId || value.generation !== this.#identity.generation) return
    if (!this.#activationStarted || this.#remoteClose) { this.#fail(); return }
    const base = ['socketId', 'generation', 'sequence', 'kind']
    const extra = value.kind === 'message' ? ['text'] : value.kind === 'close' ? ['code', 'reason', 'wasClean'] : []
    if (!['open', 'message', 'error', 'close'].includes(String(value.kind)) || !exact(value, [...base, ...extra]) || !positive(value.sequence) || value.sequence !== this.#receiveSequence + 1) { this.#fail(); return }
    this.#receiveSequence = value.sequence
    if (value.kind === 'close') {
      if (!Number.isInteger(value.code) || (value.code as number) < 1000 || (value.code as number) > 4999 || typeof value.reason !== 'string' || bytes(value.reason) > 123 || typeof value.wasClean !== 'boolean' || ([1004, 1005, 1015].includes(value.code as number)) || (value.code === 1006 && value.wasClean)) { this.#fail(); return }
      // Terminal lane is independent of incoming data credits.
      this.#remoteClose = value as unknown as Extract<SocketEvent, { kind: 'close' }>
      this.#closeTimer = setTimeout(() => this.#fail(), this.#limits.closeTimeoutMs)
      void this.#pumpReceive()
      return
    }
    if (value.kind === 'error') { this.#fail(); return }
    const size = value.kind === 'message' && typeof value.text === 'string' ? bytes(value.text) : 0
    if ((value.kind === 'message' && typeof value.text !== 'string') || size > this.#limits.maxMessageBytes || this.#incomingCount >= this.#limits.maxIncomingMessages || this.#incomingBytes + size > this.#limits.maxIncomingBytes) { this.#fail(); return }
    this.#incoming.push({ event: value as unknown as SocketEvent, bytes: size }); this.#incomingBytes += size; this.#incomingCount++
    void this.#pumpReceive()
  }
  async #pumpReceive() {
    if (this.#receiving || this.#terminal) return
    this.#receiving = true
    try {
      while (this.#incoming.length && !this.#terminal) {
        const item = this.#incoming.shift()!
        if (item.event.kind === 'open') {
          if (this.#state !== this.CONNECTING) throw new Error('Unexpected open')
          this.#state = this.OPEN; this.dispatchEvent(new Event('open'))
        } else if (item.event.kind === 'message') {
          if (this.#state !== this.OPEN) throw new Error('Message before open')
          this.dispatchEvent(new MessageEvent('message', { data: item.event.text }))
        }
        await this.#call(() => this.#host.ack(this.#identity!, item.event.sequence))
        this.#incomingBytes = Math.max(0, this.#incomingBytes - item.bytes); this.#incomingCount = Math.max(0, this.#incomingCount - 1)
      }
    } catch { this.#fail() }
    finally {
      this.#receiving = false
      if (this.#remoteClose && !this.#terminal && !this.#incoming.length) {
        this.#finish(this.#remoteClose.code, this.#remoteClose.reason, this.#remoteClose.wasClean)
        void this.#retireHost(false)
      }
    }
  }
  close(code?: number, reason = ''): void {
    if (code !== undefined && (!Number.isInteger(code) || (code !== 1000 && (code < 3000 || code > 4999)))) throw new DOMException('Invalid close code', 'InvalidAccessError')
    if (bytes(reason) > 123) throw new DOMException('Close reason too long', 'SyntaxError')
    if (this.#state === this.CLOSING || this.#terminal) return
    const connecting = this.#state === this.CONNECTING
    this.#state = this.CLOSING; this.#abort.abort()
    this.#closeRequest = { ...(code === undefined ? {} : { code }), ...(reason ? { reason: decoder.decode(encoder.encode(reason)) } : {}), abort: connecting }
    this.#closeTimer = setTimeout(() => this.#fail(), this.#limits.closeTimeoutMs)
    if (connecting) { queueMicrotask(() => this.#fail()); return }
    if (!this.#sending && !this.#queue.length) void this.#retireHost(false)
  }
  dispose(): void { if (this.#terminal) return; this.#state = this.CLOSING; this.#abort.abort(); queueMicrotask(() => this.#fail()) }
  async #retireHost(abort: boolean) {
    if (!this.#identity || this.#closingHost || this.#nativeRetired) return
    this.#closingHost = true
    const owner = this.#identity
    try {
      const receipt = await this.#call(() => this.#host.close(owner, { ...this.#closeRequest, abort: abort || this.#closeRequest.abort }), this.#limits.closeTimeoutMs)
      if (!record(receipt) || !exact(receipt, ['socketId', 'generation', 'retired']) || !same(receipt, owner) || receipt.retired !== true) throw new Error('Invalid retirement receipt')
      this.#nativeRetired = true
      if (!this.#terminal) this.#fail() // Retirement without a close event is not a clean handshake.
    } catch { this.#fence(); this.#fail() }
    finally { this.#maybeRelease() }
  }
  #fail() {
    if (this.#terminal) return
    this.#abort.abort()
    if (!this.#errorSent) { this.#errorSent = true; this.dispatchEvent(new Event('error')) }
    this.#finish(1006, '', false)
    void this.#retireHost(true)
  }
  #finish(code: number, reason: string, wasClean: boolean) {
    if (this.#terminal) return
    this.#terminal = true; this.#state = this.CLOSED
    if (this.#closeTimer !== undefined) clearTimeout(this.#closeTimer)
    this.#incoming = []; this.#incomingBytes = 0; this.#incomingCount = 0; this.#queue = []
    try { this.#unsubscribe?.() } catch { this.#fence() }
    this.#unsubscribe = null
    this.dispatchEvent(new SocketCloseEvent(code, reason, wasClean)); this.#maybeRelease()
  }
  #maybeRelease() { if (this.#terminal && this.#nativeRetired && this.#pending === 0) this.#release(this) }
}
