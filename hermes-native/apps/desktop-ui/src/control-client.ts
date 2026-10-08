/** Local settings only. This channel never represents a Hermes gateway. */
export interface LoadProfile {
  artifact_id: string
  revision: string
  model_name: string
  expected_model_path: string
  context_length: number
  cache_size: number
  cache_mode: string
  max_batch_size: number
  chunk_size: number
  vision: boolean
}

export interface ProfileSummary { profile_id: string; name: string; revision: number }
export interface SavedProfile extends ProfileSummary { profile: LoadProfile; validation_scope: 'schema' }
export interface DetachedStatus {
  state: 'detached'
  runtime_attached: false
  admission_allowed: false
  active_profile: null
  engine_observed: false
}

export interface ControlTransport {
  control<T>(operation: string, payload: object): Promise<T>
}

const MESSAGES: Readonly<Record<string, string>> = Object.freeze({
  CONTROL_UNAVAILABLE: 'Local model settings are unavailable in this session.',
  CONTROL_BUSY: 'Another local settings operation is in progress. Try again.',
  CONTROL_INVALID_REQUEST: 'The local settings request is invalid.',
  CONTROL_CONFIG_INVALID: 'Local model settings could not start because the saved launch configuration is invalid.',
  CONTROL_PROTOCOL_FAILED: 'The local settings service stopped. Restart the application to reconnect.',
  CONTROL_RETIRED: 'The local settings service stopped. Restart the application to reconnect.',
  CONTROL_TRANSPORT_FAILED: 'The local settings service stopped. Restart the application to reconnect.',
  CONTROL_CLEANUP_INCOMPLETE: 'The local settings service stopped, but cleanup could not be fully verified. Restart the application before retrying.',
  HERMES_CONTROL_UNAVAILABLE: 'Local model settings are unavailable in this session.',
  HERMES_CONTROL_FAILED: 'The local settings service stopped. Restart the application to reconnect.',
  HERMES_CONTROL_INVALID_REQUEST: 'The local settings request is invalid.',
  INVALID_PROFILE: 'Check the model folder, context, cache and chunk settings.',
  REVISION_CONFLICT: 'This profile changed in another view. Reload it before saving.',
  PROFILE_NOT_FOUND: 'This profile no longer exists. Refresh the list.',
  PROFILE_LIMIT: 'The profile limit has been reached.',
  INVALID_PARAMS: 'Check the profile name and settings.'
})

export class ControlError extends Error {
  readonly code: string
  constructor(code: string) {
    super(MESSAGES[code] ?? 'Local model settings could not be updated.')
    this.name = 'ControlError'
    this.code = code
  }
}

export function createControlClient(transport?: ControlTransport) {
  function request<T>(operation: string, payload: object): Promise<T> {
    if (!transport) return Promise.reject(new ControlError('HERMES_CONTROL_UNAVAILABLE'))
    const snapshot = structuredClone(payload)
    return transport.control<T>(operation, snapshot).catch((error: unknown) => {
      const code = error && typeof error === 'object'
        ? Object.getOwnPropertyDescriptor(error, 'code')?.value : undefined
      throw new ControlError(typeof code === 'string' && Object.hasOwn(MESSAGES, code)
        ? code : 'HERMES_CONTROL_FAILED')
    })
  }
  return {
    status: () => request<DetachedStatus>('runtime.status', {}),
    schema: () => request<object>('profiles.schema', {}),
    list: () => request<{ profiles: ProfileSummary[] }>('profiles.list', {}),
    get: (profile_id: string) => request<SavedProfile>('profiles.get', { profile_id }),
    validate: (profile: LoadProfile) => request<{ profile: LoadProfile; validation_scope: 'schema'; artifact_verified: false }>('profiles.validate', { profile }),
    save: (profile_id: string, name: string, expected_revision: number | null, profile: LoadProfile) =>
      request<{ profile_id: string; revision: number; validation_scope: 'schema' }>('profiles.save', { profile_id, name, expected_revision, profile }),
    delete: (profile_id: string, expected_revision: number) =>
      request<{ deleted: true; profile_id: string }>('profiles.delete', { profile_id, expected_revision })
  }
}

export type ControlClient = ReturnType<typeof createControlClient>
