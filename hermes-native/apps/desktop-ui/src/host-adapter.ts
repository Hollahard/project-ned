import type { HermesApiRequest } from '@hermes/upstream-global'

/** Exact native transport seam; Rust registration is a later integration gate. */
export interface NativeTransport {
  invoke<T>(command: 'hermes_host_request', payload: { method: string; args: unknown[] }): Promise<T>
  subscribe(channel: 'hermes:host:event', listener: (event: HostEvent) => void): Promise<() => void>
}

export interface HostEvent {
  name: 'backend-exit' | 'connection-applied' | 'boot-progress' | 'power-resume'
  payload: unknown
}

export class CapabilityUnavailableError extends Error {
  readonly code = 'HERMES_HOST_CAPABILITY_UNAVAILABLE'
  readonly capability: string

  constructor(capability: string) {
    super(`Hermes native feasibility host does not provide ${capability}. Native integration is pending.`)
    this.name = 'CapabilityUnavailableError'
    this.capability = capability
  }
}

export const HOST_METHODS = Object.freeze([
  'api', 'getConnection', 'getConnectionFor', 'getGatewayWsUrl',
  'getGatewayWsUrlFor', 'revalidateConnection', 'touchBackend', 'getVersion'
] as const)

type Method = typeof HOST_METHODS[number]
type UpstreamHost = Window['hermesDesktop']
export type ImplementedHost = Pick<UpstreamHost,
  Method | 'onBackendExit' | 'onConnectionApplied' | 'onBootProgress' | 'onPowerResume'>

/** Explicit subset only. Missing methods remain missing, never synthetic successes. */
export interface HostAdapter {
  bridge: ImplementedHost
  dispose(): void
  /** Await after registering a listener; rejects if native event setup failed. */
  eventSubscriptionReady(): Promise<void>
  readonly binding: 'native-injected' | 'unavailable'
}

function assertApiRequest(request: HermesApiRequest): void {
  // This is transport validation, not authorization. Native code must also
  // authorize the method, owner route and endpoint on every invocation.
  if (!request || typeof request.path !== 'string' || !request.path.startsWith('/api/')) {
    throw new TypeError('Expected a relative Hermes /api/ path')
  }
  const decoded = decodeURIComponent(request.path.split(/[?#]/, 1)[0])
  if (decoded.includes('\\') || decoded.split(/[/?#]/).some(part => part === '..')) {
    throw new TypeError('Path traversal is not a valid Hermes API request')
  }
}

export function createHostAdapter(
  transport?: NativeTransport,
  reportTransportError: (error: unknown) => void = error => console.error('[hermes-native-host] event subscription failed', error)
): HostAdapter {
  const listeners = new Map<HostEvent['name'], Set<(payload: unknown) => void>>()
  let disposed = false
  let unlisten: (() => void) | undefined
  let pendingSubscription: Promise<void> | undefined
  let subscriptionFailure: unknown

  function request<T>(method: Method, args: unknown[]): Promise<T> {
    if (disposed || !transport) return Promise.reject(new CapabilityUnavailableError(method))
    // Freeze ownership at call time, before the transport can yield.
    const payload = structuredClone({ method, args })
    return transport.invoke<T>('hermes_host_request', payload)
  }

  function subscribe(name: HostEvent['name'], callback: (payload: unknown) => void): () => void {
    if (disposed || !transport) throw new CapabilityUnavailableError(`events.${name}`)
    if (subscriptionFailure) throw subscriptionFailure
    const handlers = listeners.get(name) ?? new Set()
    handlers.add(callback)
    listeners.set(name, handlers)
    if (!pendingSubscription) {
      pendingSubscription = transport.subscribe('hermes:host:event', event => {
        if (disposed) return
        for (const handler of [...(listeners.get(event.name) ?? [])]) handler(event.payload)
      }).then(off => {
        if (disposed) off()
        else unlisten = off
      })
      // Do not manufacture a backend-exit event: a native transport failure is
      // not proof that the backend exited. The integration can await this
      // promise and the diagnostic sink also receives the original failure.
      pendingSubscription.catch(error => {
        subscriptionFailure = error
        reportTransportError(error)
      })
    }
    let subscribed = true
    return () => {
      if (!subscribed) return
      subscribed = false
      handlers.delete(callback)
      if (handlers.size === 0 && listeners.get(name) === handlers) listeners.delete(name)
    }
  }

  const bridge: ImplementedHost = {
    api: <T>(requestPayload: HermesApiRequest) => {
      assertApiRequest(requestPayload)
      return request<T>('api', [requestPayload])
    },
    getConnection: (profile, opts) => request('getConnection', [profile, opts]),
    getConnectionFor: payload => request('getConnectionFor', [payload]),
    getGatewayWsUrl: profile => request('getGatewayWsUrl', [profile]),
    getGatewayWsUrlFor: payload => request('getGatewayWsUrlFor', [payload]),
    revalidateConnection: () => request('revalidateConnection', []),
    touchBackend: (profile, options) => request('touchBackend', [profile, options]),
    getVersion: scope => request('getVersion', [scope]),
    onBackendExit: callback => subscribe('backend-exit', callback as (payload: unknown) => void),
    onConnectionApplied: callback => subscribe('connection-applied', callback),
    onBootProgress: callback => subscribe('boot-progress', callback as (payload: unknown) => void),
    onPowerResume: callback => subscribe('power-resume', callback)
  }

  return {
    bridge,
    binding: transport ? 'native-injected' : 'unavailable',
    eventSubscriptionReady: () => pendingSubscription ?? Promise.reject(new CapabilityUnavailableError('event-subscription')),
    dispose() {
      if (disposed) return
      disposed = true
      listeners.clear()
      unlisten?.()
      unlisten = undefined
    }
  }
}
