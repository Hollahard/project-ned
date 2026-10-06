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

export interface RuntimeStatus {
  core_status: string;
  inference_status: string;
  active_model?: string;
  vram_allocated_mb?: number;
  vram_total_mb?: number;
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
