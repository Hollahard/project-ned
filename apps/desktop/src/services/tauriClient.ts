import { Session, ModelProfile, RuntimeStatus } from '../types';

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
        vram_total_mb: 32768.0,
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
};
