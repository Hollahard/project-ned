import { useEffect, useRef, useState } from 'react'
import type { ControlClient, LoadProfile, ProfileSummary } from './control-client.ts'
import './model-profiles.css'

const blank = (): LoadProfile => ({ artifact_id: 'local-model', revision: 'unverified', model_name: '',
  expected_model_path: '', context_length: 2048, cache_size: 2048, cache_mode: 'FP16',
  max_batch_size: 1, chunk_size: 256, vision: false })

export function ModelProfiles({ client }: { client: ControlClient }) {
  const [profiles, setProfiles] = useState<ProfileSummary[]>([])
  const [id, setId] = useState('')
  const [name, setName] = useState('')
  const [revision, setRevision] = useState<number | null>(null)
  const [profile, setProfile] = useState<LoadProfile>(blank)
  const [busy, setBusy] = useState(false)
  const [connected, setConnected] = useState(false)
  const [message, setMessage] = useState('Connecting to local settings…')
  const [failed, setFailed] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const alive = useRef(true)
  const generation = useRef(0)

  const perform = async (action: (active: () => boolean) => Promise<string>) => {
    const started = generation.current
    const active = () => alive.current && generation.current === started
    setBusy(true); setFailed(false); setConfirmDelete(false)
    try {
      const text = await action(active)
      if (active()) setMessage(text)
    } catch (error) {
      if (active()) {
        setFailed(true)
        setMessage(error instanceof Error ? error.message : 'Local model settings could not be updated.')
      }
    } finally { if (active()) setBusy(false) }
  }

  const refresh = async (active: () => boolean) => {
    const result = await client.list()
    if (active()) setProfiles(result.profiles)
  }

  const connect = async (active: () => boolean) => {
    await client.status()
    if (!active()) return ''
    setConnected(true)
    await refresh(active)
    return 'Profiles are stored locally. No inference runtime is connected.'
  }

  useEffect(() => {
    alive.current = true
    generation.current++
    setConnected(false); setProfiles([]); setId(''); setName(''); setRevision(null)
    setProfile(blank()); setConfirmDelete(false)
    setMessage('Connecting to local settings…')
    void perform(connect)
    return () => { alive.current = false; generation.current++ }
  }, [client])

  const update = <K extends keyof LoadProfile>(key: K, value: LoadProfile[K]) =>
    setProfile(current => ({ ...current, [key]: value }))

  const reset = () => {
    setId(''); setName(''); setRevision(null); setProfile(blank()); setConfirmDelete(false)
    setFailed(false); setMessage('Enter a model folder and the settings to save.')
  }

  const select = (key: string) => void perform(async active => {
    const saved = await client.get(key)
    if (active()) {
      setId(saved.profile_id); setName(saved.name); setRevision(saved.revision); setProfile(saved.profile)
    }
    return 'Profile loaded. Model files have not been verified.'
  })

  return <section className="native-model-profiles" data-native-model-profiles>
    <header><h2>Local model profiles</h2><p>Save ExLlamaV3 context and cache settings for each local model.</p></header>
    <p className="native-model-note">Saving a profile does not load a model. Model files and available VRAM have not been checked. Weight quantization comes from the selected model files.</p>
    <div role={failed ? 'alert' : 'status'} aria-live="polite" data-native-profile-status data-failed={failed}>{message}</div>
    <div className="native-model-layout">
      <nav aria-label="Saved model profiles">
        <button type="button" disabled={busy} onClick={reset}>New profile</button>
        <button type="button" disabled={busy} onClick={() => void perform(async active => {
          if (!connected) return connect(active)
          await refresh(active); return 'Profile list refreshed.'
        })}>{connected ? 'Refresh' : 'Retry connection'}</button>
        <ul>{profiles.map(item => <li key={item.profile_id}><button type="button" disabled={busy} aria-current={id === item.profile_id ? 'true' : undefined} onClick={() => select(item.profile_id)}>{item.name}</button></li>)}</ul>
        {profiles.length === 0 && <p>No saved profiles.</p>}
      </nav>
      <form onSubmit={event => {
        event.preventDefault()
        void perform(async active => {
          const saved = await client.save(id, name, revision, profile)
          if (active()) setRevision(saved.revision)
          await refresh(active)
          return 'Profile saved locally. No model was loaded.'
        })
      }}>
        <fieldset disabled={busy || !connected}>
          <legend>Profile and model</legend>
          <label>Profile name<input name="profile-name" value={name} maxLength={128} required onChange={e => setName(e.target.value)} /></label>
          <label>Profile ID<input name="profile-id" value={id} pattern="[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}" maxLength={64} required disabled={revision !== null} onChange={e => setId(e.target.value)} /></label>
          <label>Model name<input name="model-name" value={profile.model_name} required onChange={e => update('model_name', e.target.value)} /></label>
          <label>Model folder<input name="model-folder" value={profile.expected_model_path} placeholder="C:\Models\my-exl3-model" required onChange={e => update('expected_model_path', e.target.value)} /></label>
        </fieldset>
        <fieldset disabled={busy || !connected}>
          <legend>Context and cache</legend>
          <label>Context tokens<input name="context-length" type="number" min={1} step={1} required value={profile.context_length} onChange={e => update('context_length', e.target.valueAsNumber)} /></label>
          <label>Cache tokens<input name="cache-size" type="number" min={256} step={256} required value={profile.cache_size} onChange={e => update('cache_size', e.target.valueAsNumber)} /></label>
          <label>Cache precision<select name="cache-mode" value={profile.cache_mode} onChange={e => update('cache_mode', e.target.value)}>
            <option value="FP16">FP16</option><option value="4,4">Q4</option><option value="6,6">Q6</option><option value="8,8">Q8</option>
            {!['FP16', '4,4', '6,6', '8,8'].includes(profile.cache_mode) && <option value={profile.cache_mode}>{profile.cache_mode}</option>}
          </select></label>
          <label>Prefill chunk tokens<input name="chunk-size" type="number" min={256} step={256} required value={profile.chunk_size} onChange={e => update('chunk_size', e.target.valueAsNumber)} /></label>
          <label>Maximum batch size<input name="batch-size" type="number" min={1} step={1} required value={profile.max_batch_size} onChange={e => update('max_batch_size', e.target.valueAsNumber)} /></label>
          <label className="native-model-checkbox"><input name="vision" type="checkbox" checked={profile.vision} onChange={e => update('vision', e.target.checked)} />Enable vision when supported by the model</label>
        </fieldset>
        <div className="native-model-actions">
          <button type="button" disabled={busy || !connected} onClick={() => void perform(async active => {
            const result = await client.validate(profile)
            if (active()) setProfile(result.profile)
            return 'Settings are valid. Model compatibility and VRAM use remain unchecked.'
          })}>Validate settings</button>
          <button type="submit" disabled={busy || !connected}>Save profile</button>
          {revision !== null && <button type="button" disabled={busy || !connected} onClick={() => {
            if (!confirmDelete) { setConfirmDelete(true); return }
            void perform(async active => { await client.delete(id, revision); if (active()) reset(); await refresh(active); return 'Profile deleted.' })
          }}>{confirmDelete ? 'Confirm deletion' : 'Delete profile'}</button>}
        </div>
      </form>
    </div>
  </section>
}
