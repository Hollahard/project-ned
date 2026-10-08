import React, { StrictMode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ModelProfiles } from '@native/model-profiles.tsx'
import { createControlClient, type ControlClient, type ControlTransport } from '@native/control-client.ts'
import { registerModelProfiles } from '@native/model-profiles-plugin.tsx'
import { registry } from '@retained/contrib/registry.ts'
import { $pluginDecisions, $pluginRecords, setPluginEnabled } from '@retained/contrib/plugins-store.ts'
import { SETTINGS_PLUGINS_AREA, pluginSettingsEntries, pluginSettingsRouteFrom, pluginSettingsRouteHref, pluginSettingsRouteOf, resolvePluginSettingsTarget } from '@retained/contrib/settings-pages.ts'
import { WorkerTransport } from './worker-transport.ts'

// Only unrelated host services are blocked. The plugin context, inventory,
// settings registry, route helpers and profile component are real source modules.
vi.mock('@/hermes', () => ({ pluginRest: () => { throw new Error('Unexpected Hermes backend call') }, pluginSocket: () => { throw new Error('Unexpected Hermes socket call') } }))
vi.mock('@/i18n', () => ({ createPluginI18n: () => ({}) }))
vi.mock('@/store/native-notifications', () => ({ dispatchPluginNativeNotification: () => { throw new Error('Unexpected notification') } }))

const id = 'native-model-profiles'
const disposers: (() => void)[] = []
const workers: WorkerTransport[] = []
const detached = { state: 'detached', runtime_attached: false, admission_allowed: false, active_profile: null, engine_observed: false } as const
const profile = { artifact_id: 'fixture', revision: 'schema-only', model_name: 'Fixture model', expected_model_path: 'C:/fixture/model', context_length: 2048, cache_size: 2048, cache_mode: 'FP16', max_batch_size: 1, chunk_size: 256, vision: false }

const fakeClient = (overrides: Partial<ControlClient> = {}): ControlClient => ({
  status: vi.fn().mockResolvedValue(detached), schema: vi.fn().mockResolvedValue({}),
  list: vi.fn().mockResolvedValue({ profiles: [] }), get: vi.fn(), validate: vi.fn(), save: vi.fn(), delete: vi.fn(), ...overrides,
})
const deferred = <T,>() => { let resolve!: (value: T) => void; let reject!: (error: unknown) => void; const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no }); return { promise, resolve, reject } }
async function connected() { await waitFor(() => expect(screen.getByRole('status').textContent).toContain('Profiles are stored locally')) }
function fillNew() {
  for (const [label, value] of [['Profile name', 'Small EXL3 profile'], ['Profile ID', 'small-exl3'], ['Model name', 'fixture-model'], ['Model folder', 'C:/fixture/EXL3']]) fireEvent.change(screen.getByLabelText(label), { target: { value } })
  fireEvent.change(screen.getByLabelText('Cache precision'), { target: { value: '4,4' } })
}

beforeEach(() => { window.localStorage.clear(); $pluginDecisions.set({}) })
afterEach(async () => {
  cleanup()
  for (const dispose of disposers.splice(0)) dispose()
  for (const worker of workers.splice(0)) expect(await worker.close()).toBe(0)
  vi.restoreAllMocks()
})

describe('retained settings contribution with the real Python worker', () => {
  it('registers a genuine route and persists create, update and delete across worker restart', async () => {
    const state = WorkerTransport.createState()
    const worker = new WorkerTransport(state); workers.push(worker); await worker.ready
    expect((window as any).hermesDesktop).toBeUndefined()
    const dispose = registerModelProfiles(worker); disposers.push(dispose)
    expect($pluginRecords.get()[id]).toMatchObject({ status: 'loaded', kind: 'bundled' })
    const contributions = registry.getArea(SETTINGS_PLUGINS_AREA)
    expect(contributions).toHaveLength(1)
    expect(contributions[0]).toMatchObject({ id: 'native-model-profiles:profiles', source: 'plugin:native-model-profiles' })
    const entries = pluginSettingsEntries({ contributions, rows: [], configTitle: 'Agent settings' })
    const href = pluginSettingsRouteHref(pluginSettingsRouteOf(entries[0]))
    expect(href).toBe('/settings?tab=plugins&plugin=native-model-profiles%3Aprofiles')
    const target = resolvePluginSettingsTarget(entries, pluginSettingsRouteFrom(new URL(href, 'https://fixture.invalid').searchParams))
    expect(target?.entry).toBe(entries[0])
    const view = render(<>{target!.entry.render!()}</>); await connected()
    fillNew()
    fireEvent.click(screen.getByRole('button', { name: 'Validate settings' }))
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('Settings are valid'))
    fireEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('Profile saved locally'))
    const created: any = await worker.control('profiles.get', { profile_id: 'small-exl3' })
    expect(created.profile.cache_mode).toBe('4,4')
    expect(created.profile.context_length).toBe(2048)
    expect(created.revision).toBe(1)
    fireEvent.change(screen.getByLabelText('Context tokens'), { target: { value: '4096' } })
    fireEvent.change(screen.getByLabelText('Cache tokens'), { target: { value: '4096' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    await waitFor(() => expect(worker.calls.filter(call => call.operation === 'profiles.save')).toHaveLength(2))
    await waitFor(() => expect((screen.getByRole('button', { name: 'Save profile' }) as HTMLButtonElement).disabled).toBe(false))
    const saves = worker.calls.filter(call => call.operation === 'profiles.save')
    expect(saves.map(call => call.payload.expected_revision)).toEqual([null, 1])
    view.unmount(); dispose(); disposers.splice(disposers.indexOf(dispose), 1)
    expect(await worker.close()).toBe(0); workers.splice(workers.indexOf(worker), 1)
    const reopened = new WorkerTransport(state); workers.push(reopened); await reopened.ready
    const disposeReopened = registerModelProfiles(reopened); disposers.push(disposeReopened)
    const newEntries = pluginSettingsEntries({ contributions: registry.getArea(SETTINGS_PLUGINS_AREA), rows: [], configTitle: 'Agent settings' })
    render(<>{newEntries[0].render!()}</>); await connected()
    fireEvent.click(screen.getByRole('button', { name: 'Small EXL3 profile' }))
    await waitFor(() => expect((screen.getByLabelText('Context tokens') as HTMLInputElement).value).toBe('4096'))
    fireEvent.click(screen.getByRole('button', { name: 'Delete profile' }))
    expect(reopened.calls.some(call => call.operation === 'profiles.delete')).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: 'Confirm deletion' }))
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('Profile deleted.'))
    expect(reopened.calls.find(call => call.operation === 'profiles.delete')?.payload.expected_revision).toBe(2)
    expect((screen.getByLabelText('Profile ID') as HTMLInputElement).value).toBe('')
    await expect(reopened.control('profiles.list', {})).resolves.toEqual({ profiles: [] })
    expect(reopened.calls.every(call => /^(runtime\.status|profiles\.(list|get|validate|save|delete))$/.test(call.operation))).toBe(true)
  })

  it('uses retained enable/disable decisions and removes registrations on teardown', async () => {
    const dispose = registerModelProfiles(); disposers.push(dispose)
    await setPluginEnabled(id, false)
    expect(registry.getArea(SETTINGS_PLUGINS_AREA)).toHaveLength(0)
    expect($pluginRecords.get()[id].status).toBe('disabled')
    expect(JSON.parse(window.localStorage.getItem('hermes.desktop.pluginDecisions.v2')!)[id]).toBe(false)
    await setPluginEnabled(id, true); await setPluginEnabled(id, true)
    expect(registry.getArea(SETTINGS_PLUGINS_AREA)).toHaveLength(1)
    dispose(); disposers.splice(disposers.indexOf(dispose), 1)
    expect(registry.getArea(SETTINGS_PLUGINS_AREA)).toHaveLength(0)
    expect($pluginRecords.get()[id]).toBeUndefined()
    $pluginDecisions.set({ [id]: false })
    disposers.push(registerModelProfiles())
    expect(registry.getArea(SETTINGS_PLUGINS_AREA)).toHaveLength(0)
    expect($pluginRecords.get()[id].status).toBe('disabled')
  })

  it('preserves a newer real SQLite revision until the stale editor reloads it', async () => {
    const worker = new WorkerTransport(WorkerTransport.createState()); workers.push(worker); await worker.ready
    await worker.control('profiles.save', { profile_id: 'conflict', name: 'Conflict fixture', expected_revision: null, profile })
    render(<ModelProfiles client={createControlClient(worker)} />); await connected()
    fireEvent.click(screen.getByRole('button', { name: 'Conflict fixture' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Delete profile' })).toBeDefined())
    await worker.control('profiles.save', { profile_id: 'conflict', name: 'Conflict fixture', expected_revision: 1, profile: { ...profile, context_length: 4096, cache_size: 4096 } })
    fireEvent.change(screen.getByLabelText('Model name'), { target: { value: 'STALE EDIT' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    await waitFor(() => expect(screen.getByRole('alert').textContent).toBe('This profile changed in another view. Reload it before saving.'))
    const saved: any = await worker.control('profiles.get', { profile_id: 'conflict' })
    expect(saved.revision).toBe(2)
    expect(saved.profile.model_name).toBe('Fixture model')
    fireEvent.click(screen.getByRole('button', { name: 'Conflict fixture' }))
    await waitFor(() => expect((screen.getByLabelText('Context tokens') as HTMLInputElement).value).toBe('4096'))
  })
})

describe('profile renderer lifecycle and bounded public errors', () => {
  it('renders a truthful unavailable state without a Hermes connection', async () => {
    render(<ModelProfiles client={createControlClient()} />)
    await waitFor(() => expect(screen.getByRole('alert').textContent).toBe('Local model settings are unavailable in this session.'))
    expect((screen.getByRole('button', { name: 'Save profile' }) as HTMLButtonElement).disabled).toBe(true)
    expect((window as any).hermesDesktop).toBeUndefined()
  })

  it('retries an initially busy local connection without remounting or launching a backend', async () => {
    let statusCalls = 0
    const transport: ControlTransport = { control: vi.fn(async (operation: string) => {
      if (operation === 'runtime.status') {
        if (++statusCalls === 1) throw { code: 'CONTROL_BUSY', message: 'PRIVATE CANARY' }
        return detached
      }
      if (operation === 'profiles.list') return { profiles: [] }
      throw new Error('Unexpected operation')
    }) as ControlTransport['control'] }
    render(<ModelProfiles client={createControlClient(transport)} />)
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('progress'))
    expect(screen.getByRole('alert').textContent).not.toContain('PRIVATE CANARY')
    expect((screen.getByRole('button', { name: 'Save profile' }) as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: 'Retry connection' }))
    await connected()
    expect(statusCalls).toBe(2)
    expect((screen.getByRole('button', { name: 'Save profile' }) as HTMLButtonElement).disabled).toBe(false)
    expect((window as any).hermesDesktop).toBeUndefined()
  })

  it('maps actual worker missing/revision errors and does not expose raw messages', async () => {
    const transport: ControlTransport = { control: vi.fn().mockRejectedValue({ code: 'PROFILE_NOT_FOUND', message: 'PRIVATE CANARY' }) }
    await expect(createControlClient(transport).get('gone')).rejects.toThrow('This profile no longer exists. Refresh the list.')
    transport.control = vi.fn().mockRejectedValue({ code: 'REVISION_CONFLICT', message: 'PRIVATE CANARY' })
    await expect(createControlClient(transport).save('a', 'a', 1, profile)).rejects.toThrow('This profile changed in another view. Reload it before saving.')
    transport.control = vi.fn().mockRejectedValue({ code: 'UNRECOGNIZED CANARY', message: 'PRIVATE CANARY' })
    await expect(createControlClient(transport).status()).rejects.toThrow('The local settings service stopped. Restart the application to reconnect.')
  })

  it('ignores stale initialization responses through StrictMode and client replacement', async () => {
    const first = deferred<{ profiles: any[] }>()
    const oldClient = fakeClient({ list: vi.fn().mockReturnValue(first.promise) })
    const view = render(<StrictMode><ModelProfiles client={oldClient} /></StrictMode>)
    await waitFor(() => expect(oldClient.list).toHaveBeenCalled())
    const current = fakeClient()
    view.rerender(<StrictMode><ModelProfiles client={current} /></StrictMode>); await connected()
    await act(async () => first.resolve({ profiles: [{ profile_id: 'stale', name: 'STALE PROFILE', revision: 1 }] }))
    expect(screen.queryByRole('button', { name: 'STALE PROFILE' })).toBeNull()
    expect((screen.getByRole('button', { name: 'Save profile' }) as HTMLButtonElement).disabled).toBe(false)
  })

  it('disables mutation after replacing a connected client with an unavailable one', async () => {
    const view = render(<ModelProfiles client={fakeClient()} />); await connected()
    view.rerender(<ModelProfiles client={createControlClient()} />)
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('unavailable'))
    expect((screen.getByRole('button', { name: 'Save profile' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('clears a deleted selection even if refreshing the list fails afterwards', async () => {
    const client = fakeClient({
      list: vi.fn().mockResolvedValueOnce({ profiles: [{ profile_id: 'fixture', name: 'Fixture', revision: 7 }] }).mockRejectedValueOnce(new Error('List failed')),
      get: vi.fn().mockResolvedValue({ profile_id: 'fixture', name: 'Fixture', revision: 7, profile, validation_scope: 'schema' }),
      delete: vi.fn().mockResolvedValue({ deleted: true, profile_id: 'fixture' }),
    })
    render(<ModelProfiles client={client} />); await connected()
    fireEvent.click(screen.getByRole('button', { name: 'Fixture' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Delete profile' })).toBeDefined())
    fireEvent.click(screen.getByRole('button', { name: 'Delete profile' }))
    fireEvent.click(screen.getByRole('button', { name: 'Confirm deletion' }))
    await waitFor(() => expect(screen.getByRole('alert').textContent).toBe('List failed'))
    expect(client.delete).toHaveBeenCalledWith('fixture', 7)
    expect((screen.getByLabelText('Profile ID') as HTMLInputElement).value).toBe('')
    expect(screen.queryByRole('button', { name: 'Delete profile' })).toBeNull()
  })
})
