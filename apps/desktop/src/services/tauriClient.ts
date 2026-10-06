import {
  Session,
  ModelProfile,
  RuntimeStatus,
  GpuTelemetry,
  GamingModeStatus,
  PreflightRequest,
  PreflightResult,
} from '../types';

// Detect if running inside Tauri desktop webview
const isTauri = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;

async function tauriInvoke<T>(cmd: string, args: Record<string, any> = {}): Promise<T> {
  if (isTauri) {
    const { invoke } = await import('@tauri-apps/api/core');
    return invoke<T>(cmd, args);
  }

  // Browser dev fallback / mock fixtures
  console.debug(`[MockTauri] Invoking ${cmd}`, args);
  switch (cmd) {
    case 'get_runtime_status':
      return {
        core_status: 'ok',
        inference_status: 'ok',
        active_model: 'Mistral-Small-3.1-24B-Instruct-2503-exl3',
        vram_allocated_mb: 18450.0,
        vram_total_mb: 32607.0,
        gpu_telemetry: {
          available: true,
          device_name: 'NVIDIA GeForce RTX 5090',
          driver_version: '572.16',
          nvml_version: '12.572.16',
          vram_total_mb: 32607.0,
          vram_used_mb: 18450.0,
          vram_free_mb: 14157.0,
          vram_usage_percent: 56.6,
          temperature_c: 34,
          power_watts: 85.0,
        },
        gaming_mode: {
          active: false,
          activated_at: null,
          elapsed_seconds: 0.0,
          vram_freed_mb: 0.0,
          message: 'Gaming Mode is inactive',
        },
      } as T;
    case 'get_gpu_telemetry':
      return {
        available: true,
        device_name: 'NVIDIA GeForce RTX 5090',
        driver_version: '572.16',
        nvml_version: '12.572.16',
        vram_total_mb: 32607.0,
        vram_used_mb: 2100.0,
        vram_free_mb: 30507.0,
        vram_usage_percent: 6.4,
        temperature_c: 32,
        power_watts: 75.0,
        power_limit_watts: 600.0,
        utilization_gpu_percent: 0,
        utilization_mem_percent: 2,
      } as T;
    case 'activate_gaming_mode':
      return {
        active: true,
        activated_at: Date.now() / 1000,
        elapsed_seconds: 0.18,
        vram_freed_mb: 18450.0,
        message: 'Gaming Mode ACTIVE. VRAM evacuated in 0.180s. GPU memory returned to Windows baseline.',
      } as T;
    case 'deactivate_gaming_mode':
      return {
        active: false,
        activated_at: null,
        elapsed_seconds: 0.0,
        vram_freed_mb: 0.0,
        message: 'Gaming Mode deactivated. Models can now be loaded.',
      } as T;
    case 'get_gaming_mode_status':
      return {
        active: false,
        activated_at: null,
        elapsed_seconds: 0.0,
        vram_freed_mb: 0.0,
        message: 'Gaming Mode is inactive',
      } as T;
    case 'check_vram_preflight':
      return {
        fits: true,
        model_name: args.request?.model_name || 'Mistral-Small-3.1-24B-Instruct-2503-exl3',
        context_length: args.request?.context_length || 32768,
        kv_cache_dtype: args.request?.kv_cache_dtype || 'q6',
        estimated_weights_mb: 18000.0,
        estimated_kv_cache_mb: 1200.0,
        estimated_total_mb: 20700.0,
        available_vram_mb: 32000.0,
        headroom_mb: 11300.0,
        recommended_context: null,
        recommended_kv_cache: null,
        message: 'Preflight PASSED: Fits safely on RTX 5090.',
      } as T;
    case 'list_models':
      return [
        {
          id: 'Mistral-Small-3.1-24B-Instruct-2503-exl3',
          name: 'Mistral Small 24B (EXL3)',
          parameters_b: 24.0,
          resident: true,
          loaded: true,
          vram_estimate_mb: 18500,
        },
        {
          id: 'Qwen3-30B-A3B-Instruct-2507',
          name: 'Qwen3 30B (EXL3)',
          parameters_b: 30.0,
          resident: true,
          loaded: false,
          vram_estimate_mb: 22000,
        },
      ] as T;
    case 'list_sessions':
      return [
        {
          id: 'session-default',
          title: 'Welcome to Project Friday',
          created_at: Date.now() / 1000,
          updated_at: Date.now() / 1000,
          working_directory: 'G:\\Project_Ned',
          model_profile: 'Mistral-Small-3.1-24B',
        },
      ] as T;
    case 'create_session':
      return {
        id: `session-${Date.now()}`,
        title: args.title || 'New Session',
        created_at: Date.now() / 1000,
        updated_at: Date.now() / 1000,
        working_directory: 'G:\\Project_Ned',
        model_profile: 'default',
      } as T;
    case 'cancel_turn':
      return undefined as T;
    default:
      return {} as T;
  }
}

export const TauriClient = {
  getRuntimeStatus: () => tauriInvoke<RuntimeStatus>('get_runtime_status'),
  listModels: () => tauriInvoke<ModelProfile[]>('list_models'),
  loadModel: (modelId: string) => tauriInvoke<any>('load_model', { modelId }),
  unloadModel: () => tauriInvoke<any>('unload_model'),
  listSessions: () => tauriInvoke<Session[]>('list_sessions'),
  createSession: (title?: string) => tauriInvoke<Session>('create_session', { title }),
  cancelTurn: (sessionId: string) => tauriInvoke<void>('cancel_turn', { sessionId }),
  getGpuTelemetry: () => tauriInvoke<GpuTelemetry>('get_gpu_telemetry'),
  checkVramPreflight: (request: PreflightRequest) =>
    tauriInvoke<PreflightResult>('check_vram_preflight', { request }),
  activateGamingMode: () => tauriInvoke<GamingModeStatus>('activate_gaming_mode'),
  deactivateGamingMode: () => tauriInvoke<GamingModeStatus>('deactivate_gaming_mode'),
  getGamingModeStatus: () => tauriInvoke<GamingModeStatus>('get_gaming_mode_status'),
};
