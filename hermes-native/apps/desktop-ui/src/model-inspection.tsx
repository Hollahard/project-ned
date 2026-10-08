import type { ModelInspection } from './model-inspection-client.ts'

const STATUS: Record<ModelInspection['status'], string> = {
  metadata_inspected: 'Metadata inspected', incomplete: 'Model files are incomplete',
  security: 'Inspection refused', changed: 'Files changed during inspection',
  invalid: 'Invalid model metadata', inaccessible: 'Model files are inaccessible',
  unsupported: 'Some model metadata is unsupported',
}

export function ModelInspectionResult({ result }: { result: ModelInspection }) {
  return <section className="native-model-inspection" aria-label="Model metadata inspection" data-native-model-inspection>
    <h3>{STATUS[result.status]}</h3>
    <dl>
      <dt>Declared format</dt><dd>{result.format}</dd>
      <dt>Declared weight bits</dt><dd>{result.declared_bits ?? 'Not declared'}</dd>
      <dt>Declared architecture</dt><dd>{result.declared_architectures.join(', ') || 'Not declared'}</dd>
      <dt>Observed tensor entries</dt><dd>{result.observed_tensor_count}{result.index_tensor_count === null ? '' : ` of ${result.index_tensor_count} indexed`}</dd>
    </dl>
    {result.missing_shards.length > 0 && <div role="alert"><strong>Missing weight shards</strong>
      <ul>{result.missing_shards.map(name => <li key={name}>{name}</li>)}</ul>
    </div>}
    {result.issues.length > 0 && <details><summary>Inspection details</summary><ul>
      {result.issues.map((issue, index) => <li key={index}>{issue.code}{issue.file ? ` — ${issue.file}` : ''}</li>)}
    </ul>{result.issues_truncated && <p>Additional diagnostic items were omitted.</p>}</details>}
    <p>Only metadata and weight headers were inspected. Runtime compatibility and VRAM use remain unchecked. No model was loaded.</p>
    {result.metadata_fingerprint && <details><summary>{result.fingerprint_partial ? 'Partial metadata fingerprint' : 'Metadata fingerprint'}</summary>
      <code>{result.metadata_fingerprint}</code><p>This covers metadata, weight headers and file sizes. It does not hash weight contents or certify a load.</p>
    </details>}
  </section>
}
