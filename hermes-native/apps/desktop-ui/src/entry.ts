import { bootstrapRetainedRenderer } from './bootstrap.ts'

const notice = document.createElement('aside')
notice.id = 'hermes-native-feasibility-notice'
notice.textContent = 'Hermes native feasibility build — partial host adapter; no runtime is started; native browser, terminal and parity verification pending.'
notice.setAttribute('role', 'status')
Object.assign(notice.style, {
  position: 'fixed', bottom: '0', left: '0', right: '0', zIndex: '2147483647',
  padding: '8px 12px', color: '#fff', background: '#533300', font: '12px system-ui'
})
document.body.appendChild(notice)

void bootstrapRetainedRenderer(window, () => import('@hermes-native/retained-entry')).then(adapter => {
  window.addEventListener('pagehide', () => adapter.dispose(), { once: true })
}).catch(error => {
  notice.textContent = `Hermes native feasibility initialization stopped: ${error instanceof Error ? error.message : String(error)}`
  console.error('[hermes-native-feasibility]', error)
})
