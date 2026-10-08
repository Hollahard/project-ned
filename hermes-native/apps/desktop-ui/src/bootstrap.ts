import { createHostAdapter, type HostAdapter, type NativeTransport } from './host-adapter.ts'

export interface BootstrapTarget {
  hermesDesktop?: object
  __HERMES_NATIVE_TRANSPORT__?: NativeTransport
}

/** Install before evaluating any of upstream main.tsx's store side effects. */
export async function bootstrapRetainedRenderer(
  target: BootstrapTarget,
  loadRenderer: () => Promise<unknown>
): Promise<HostAdapter> {
  if (target.hermesDesktop) throw new Error('Refusing to replace an existing Hermes host bridge')
  const adapter = createHostAdapter(target.__HERMES_NATIVE_TRANSPORT__)
  Object.defineProperty(target, 'hermesDesktop', {
    configurable: true,
    enumerable: true,
    value: adapter.bridge
  })
  try {
    await loadRenderer()
    return adapter
  } catch (error) {
    adapter.dispose()
    throw error
  }
}
