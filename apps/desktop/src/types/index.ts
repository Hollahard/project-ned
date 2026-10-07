/**
 * Project Friday Desktop Types & Contract Interfaces
 */

export interface Session {
  id: string;
  title: string;
  created_at: number;
  updated_at: number;
  working_directory: string;
  model_profile: string;
}

export interface ChatMessage {
  id?: string;
  role: 'user' | 'assistant' | 'system' | 'tool';
  content: string;
  tool_calls?: ToolCall[];
  tool_call_id?: string;
  created_at?: number;
}

export interface ToolCall {
  id: string;
  type: string;
  function: {
    name: string;
    arguments: string;
  };
}

export interface ModelProfile {
  id: string;
  name: string;
  parameters_b?: number;
  resident: boolean;
  loaded: boolean;
  vram_estimate_mb?: number;
}

export interface GpuTelemetry {
  available: boolean;
  device_name: string;
  driver_version?: string;
  nvml_version?: string;
  vram_total_mb: number;
  vram_used_mb: number;
  vram_free_mb: number;
  vram_usage_percent: number;
  temperature_c: number;
  power_watts: number;
  power_limit_watts?: number;
  utilization_gpu_percent?: number;
  utilization_mem_percent?: number;
}

export interface GamingModeStatus {
  active: boolean;
  activated_at?: number | null;
  elapsed_seconds: number;
  vram_freed_mb: number;
  message: string;
}

export interface PreflightRequest {
  model_name: string;
  context_length?: number;
  kv_cache_dtype?: string;
  available_vram_mb?: number;
  bpw?: number;
}

export interface PreflightResult {
  fits: boolean;
  model_name: string;
  context_length: number;
  kv_cache_dtype: string;
  estimated_weights_mb: number;
  estimated_kv_cache_mb: number;
  estimated_total_mb: number;
  available_vram_mb: number;
  headroom_mb: number;
  recommended_context?: number | null;
  recommended_kv_cache?: string | null;
  message: string;
}

export interface RuntimeStatus {
  core_status: string;
  inference_status: string;
  active_model?: string;
  vram_allocated_mb?: number;
  vram_total_mb?: number;
  gpu_telemetry?: GpuTelemetry;
  gaming_mode?: GamingModeStatus;
}

export interface EventEnvelope {
  event_id: string;
  timestamp: string;
  session_id: string;
  turn_id: string;
  type:
    | 'turn.started'
    | 'prompt.prefill'
    | 'reasoning.delta'
    | 'assistant.delta'
    | 'tool.requested'
    | 'approval.required'
    | 'tool.started'
    | 'tool.completed'
    | 'usage'
    | 'turn.completed'
    | 'turn.cancelled'
    | 'error';
  payload: Record<string, any>;
}

export interface FirstLaunchStatus {
  is_first_launch: boolean;
  workspace_root: string | null;
  config_exists: boolean;
  configured_model: string | null;
}

export interface DiagnosticCheck {
  id: string;
  name: string;
  category: 'gpu' | 'job_object' | 'os' | 'storage' | 'sidecar';
  status: 'pass' | 'warn' | 'fail';
  details: string;
  recommended_action?: string | null;
}

export interface FirstLaunchDiagnostics {
  overall_status: 'pass' | 'warn' | 'fail';
  gpu_detected: boolean;
  gpu_name: string;
  vram_total_mb: number;
  job_object_supported: boolean;
  checks: DiagnosticCheck[];
}

export interface FirstLaunchSetupRequest {
  workspace_root: string;
  model_profile: string;
  kv_cache_dtype: 'q6' | 'q8' | 'fp16';
  context_length: number;
  enable_gaming_mode?: boolean;
}

export interface FirstLaunchSetupResponse {
  success: boolean;
  message: string;
  workspace_root: string;
  initialized_at: string;
}

