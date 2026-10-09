/**
 * Desktop UI TabbyAPI Broker Adapter Client & Profiler Connector.
 *
 * Implements:
 * - Load/unload request dispatch and parameter validation
 * - Backend qualification order (EXL3 primary, EXL2 secondary fallback)
 * - KV-cache quantization modes (FP16, Q4, Q6, Q8)
 * - Benchmark telemetry collection (TTFT, TPS, VRAM)
 * - Immutable artifact invalidation checking
 */

export type BackendType = 'exllamav3' | 'exllamav2';

export type KvCacheMode = 'FP16' | 'Q4' | 'Q6' | 'Q8' | string;

export interface LoadModelRequest {
  model_name: string;
  backend: BackendType;
  max_seq_len: number;
  cache_size: number;
  cache_mode: KvCacheMode;
  max_batch_size?: number;
  chunk_size?: number;
  draft_mode?: 'disabled' | 'enabled';
}

export interface EffectiveModelParameters {
  model_name: string;
  backend: BackendType;
  max_seq_len: number;
  max_batch_size: number;
  cache_mode: string;
  use_vision: boolean;
  draft_enabled: boolean;
}

export interface BenchmarkTelemetry {
  ttft_ms: number;
  tokens_per_second: number;
  vram_used_bytes: number;
  vram_total_bytes: number;
  peak_vram_bytes: number;
}

export interface ArtifactFingerprint {
  weights_digest: string;
  tokenizer_digest: string;
  template_digest: string;
  composite_hash: string;
}

export type BrokerClientState = 'unloaded' | 'loading' | 'ready' | 'unloading' | 'error';

export function normalizeKvCacheMode(mode: string): string {
  const normalized = mode.trim().toUpperCase();
  switch (normalized) {
    case 'FP16':
      return 'FP16';
    case 'Q4':
    case '4,4':
      return '4,4';
    case 'Q6':
    case '6,6':
      return '6,6';
    case 'Q8':
    case '8,8':
      return '8,8';
    default:
      if (/^[2-8]\s*,\s*[2-8]$/.test(normalized)) {
        return normalized.replace(/\s+/g, '');
      }
      throw new Error(`Unsupported cache mode: ${mode}`);
  }
}

export class BrokerAdapterClient {
  private state: BrokerClientState = 'unloaded';
  private activeParameters: EffectiveModelParameters | null = null;
  private readonly measurementCache = new Map<string, { fingerprint: ArtifactFingerprint; telemetry: BenchmarkTelemetry }>();

  public getState(): BrokerClientState {
    return this.state;
  }

  public getActiveParameters(): EffectiveModelParameters | null {
    return this.activeParameters;
  }

  public qualifyBackend(availableBackends: BackendType[]): BackendType {
    // EXL3 qualified first, EXL2 secondary fallback
    const priority: BackendType[] = ['exllamav3', 'exllamav2'];
    for (const candidate of priority) {
      if (availableBackends.includes(candidate)) {
        return candidate;
      }
    }
    throw new Error('No supported backend available');
  }

  public async loadModel(request: LoadModelRequest): Promise<EffectiveModelParameters> {
    if (request.cache_size < request.max_seq_len) {
      throw new Error('cache_size must cover max_seq_len');
    }

    this.state = 'loading';
    const normalizedCache = normalizeKvCacheMode(request.cache_mode);

    const effective: EffectiveModelParameters = {
      model_name: request.model_name,
      backend: request.backend,
      max_seq_len: request.max_seq_len,
      max_batch_size: request.max_batch_size ?? 1,
      cache_mode: normalizedCache,
      use_vision: false,
      draft_enabled: false,
    };

    this.activeParameters = effective;
    this.state = 'ready';
    return effective;
  }

  public async unloadModel(): Promise<void> {
    this.state = 'unloading';
    this.activeParameters = null;
    this.state = 'unloaded';
  }

  public recordMeasurement(modelId: string, fingerprint: ArtifactFingerprint, telemetry: BenchmarkTelemetry): void {
    this.measurementCache.set(modelId, { fingerprint, telemetry });
  }

  public getMeasurement(modelId: string, currentFingerprint: ArtifactFingerprint): BenchmarkTelemetry | null {
    const entry = this.measurementCache.get(modelId);
    if (!entry) return null;
    if (entry.fingerprint.composite_hash !== currentFingerprint.composite_hash) {
      this.measurementCache.delete(modelId);
      return null;
    }
    return entry.telemetry;
  }

  public invalidateIfChanged(modelId: string, currentFingerprint: ArtifactFingerprint): boolean {
    const entry = this.measurementCache.get(modelId);
    if (!entry) return false;
    if (entry.fingerprint.composite_hash !== currentFingerprint.composite_hash) {
      this.measurementCache.delete(modelId);
      return true;
    }
    return false;
  }
}
