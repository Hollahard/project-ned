import { bootstrapRetainedRenderer, type BootstrapTarget } from './bootstrap.ts'

const notice = document.createElement('aside')
notice.id = 'hermes-native-feasibility-notice'
notice.textContent = 'Hermes native feasibility build — partial host adapter; no runtime is started; native browser, terminal and parity verification pending.'
notice.setAttribute('role', 'status')
Object.assign(notice.style, {
  position: 'fixed', bottom: '0', left: '0', right: '0', zIndex: '2147483647',
  padding: '8px 12px', color: '#fff', background: '#533300', font: '12px system-ui'
})
document.body.appendChild(notice)

void bootstrapRetainedRenderer(window, () => import('@hermes-native/retained-entry')).then(async adapter => {
  try {
  const { registerModelProfiles } = await import('./model-profiles-plugin.tsx')
  const transport = (window as BootstrapTarget).__HERMES_NATIVE_TRANSPORT__
  const unregister = registerModelProfiles(transport?.control ? {
    control: transport.control.bind(transport),
    inspectModel: transport.inspectModel?.bind(transport),
  } : undefined)
  notice.dataset.bootstrap = 'resolved'
  notice.dataset.modelProfiles = 'registered'
  window.addEventListener('pagehide', () => { unregister(); adapter.dispose() }, { once: true })
  } catch (error) { adapter.dispose(); throw error }
}).catch(error => {
  notice.dataset.bootstrap = 'stopped'
  notice.textContent = `Hermes native feasibility initialization stopped: ${error instanceof Error ? error.message : String(error)}`
  console.error('[hermes-native-feasibility]', error)
})
