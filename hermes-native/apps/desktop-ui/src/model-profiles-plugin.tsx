import { createPluginContext } from '@hermes-native/plugin-context'
import { dropPlugin, pluginActive, publishPlugin } from '@hermes-native/plugin-inventory'
import { createControlClient, type ControlTransport } from './control-client.ts'
import { ModelProfiles } from './model-profiles.tsx'

/** Use Hermes's existing settings contribution and enable/disable lifecycle. */
export function registerModelProfiles(transport?: ControlTransport): () => void {
  const id = 'native-model-profiles'
  const record = { id, name: 'Local model profiles', description: 'Saved ExLlamaV3 context and cache settings.', kind: 'bundled' as const }
  const client = createControlClient(transport)
  let disposers: (() => void)[] = []
  const deactivate = () => { disposers.forEach(off => off()); disposers = [] }
  const activate = () => {
    deactivate()
    const context = createPluginContext(id, off => disposers.push(off))
    context.registerSettingsPage({ id: 'profiles', title: 'Local model profiles', icon: 'settings-gear',
      render: () => <ModelProfiles client={client} /> })
    publishPlugin({ ...record, status: 'loaded' })
  }
  publishPlugin({ ...record, status: 'disabled' }, { activate, deactivate })
  try { if (pluginActive(id)) activate() }
  catch (error) { deactivate(); dropPlugin(id); throw error }
  return () => { deactivate(); dropPlugin(id) }
}
