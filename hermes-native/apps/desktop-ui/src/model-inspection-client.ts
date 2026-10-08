/** Observed metadata only. Inspection never grants filesystem access or admits a load. */
export interface ModelInspection {
  schema: 1
  model: string
  status: 'metadata_inspected' | 'security' | 'changed' | 'invalid' | 'incomplete' | 'inaccessible' | 'unsupported'
  format: string
  declared_architectures: string[]
  declared_bits: number | null
  observed_tensor_count: number
  observed_shard_count: number
  bytes_read: number
  index_tensor_count: number | null
  missing_shards: string[]
  metadata_fingerprint: string | null
  fingerprint_partial: boolean
  fingerprint_scope: 'metadata_files_weight_headers_and_file_sizes'
  issues: { code: string; category: string; file?: string }[]
  issues_truncated: boolean
  runtime_compatible: null
  load_certified: false
  weights_content_hashed: false
  weight_payload_bytes_read: 0
}

export interface ModelInspectionTransport {
  inspectModel(modelPath: string): Promise<ModelInspection>
}

const MESSAGES: Readonly<Record<string, string>> = Object.freeze({
  CATALOG_UNAVAILABLE: 'Model inspection is unavailable. This session has no host-approved model folder.',
  CATALOG_BUSY: 'Another model inspection is in progress. Try again when it finishes.',
  CATALOG_INVALID_REQUEST: 'Enter an immediate model folder inside a host-approved directory.',
  CATALOG_CONFIG_INVALID: 'Model inspection could not start because its host configuration is invalid.',
  CATALOG_OUTSIDE_GRANT: 'This model folder is outside the directories approved by the host.',
  CATALOG_RETIRED: 'Model inspection stopped for this window. Restart the application to inspect again.',
  CATALOG_TRANSPORT_FAILED: 'Model inspection stopped or exceeded its time limit. No model was loaded.',
  CATALOG_FAILED: 'Model metadata could not be inspected. No model was loaded.',
  CATALOG_PROTOCOL_FAILED: 'The model inspection service returned an invalid result.',
  CATALOG_CLEANUP_INCOMPLETE: 'Model inspection stopped, but process cleanup could not be verified.',
})

export class ModelInspectionError extends Error {
  readonly code: string
  constructor(code: string) {
    super(MESSAGES[code] ?? MESSAGES.CATALOG_FAILED)
    this.name = 'ModelInspectionError'
    this.code = code
  }
}

export function createModelInspector(transport?: Partial<ModelInspectionTransport>) {
  return {
    async inspect(modelPath: string): Promise<ModelInspection> {
      if (!transport?.inspectModel) throw new ModelInspectionError('CATALOG_UNAVAILABLE')
      try { return await transport.inspectModel(modelPath) }
      catch (error: unknown) {
        const code = error && typeof error === 'object'
          ? Object.getOwnPropertyDescriptor(error, 'code')?.value : undefined
        throw new ModelInspectionError(typeof code === 'string' && Object.hasOwn(MESSAGES, code)
          ? code : 'CATALOG_FAILED')
      }
    }
  }
}

export type ModelInspector = ReturnType<typeof createModelInspector>
