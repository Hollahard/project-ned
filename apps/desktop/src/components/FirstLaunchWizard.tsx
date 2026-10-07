import React, { useState, useEffect } from 'react';
import {
  FirstLaunchDiagnostics,
  FirstLaunchSetupRequest,
  FirstLaunchSetupResponse,
} from '../types';
import { TauriClient } from '../services/tauriClient';

interface FirstLaunchWizardProps {
  onComplete: (response: FirstLaunchSetupResponse) => void;
  onCancel?: () => void;
  isInitialSetup?: boolean;
}

export const FirstLaunchWizard: React.FC<FirstLaunchWizardProps> = ({
  onComplete,
  onCancel,
  isInitialSetup = true,
}) => {
  const [currentStep, setCurrentStep] = useState<number>(1);
  const [diagnostics, setDiagnostics] = useState<FirstLaunchDiagnostics | null>(null);
  const [diagnosticsLoading, setDiagnosticsLoading] = useState<boolean>(false);
  const [diagnosticsError, setDiagnosticsError] = useState<string | null>(null);

  // Setup form state
  const [workspaceRoot, setWorkspaceRoot] = useState<string>('G:\\Project_Ned');
  const [modelProfile, setModelProfile] = useState<string>(
    'Mistral-Small-3.1-24B-Instruct-2503-exl3'
  );
  const [kvCacheDtype, setKvCacheDtype] = useState<'q6' | 'q8' | 'fp16'>('q6');
  const [contextLength, setContextLength] = useState<number>(32768);
  const [enableGamingMode, setEnableGamingMode] = useState<boolean>(true);
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  // Load diagnostics when advancing to step 2
  const runDiagnostics = async () => {
    setDiagnosticsLoading(true);
    setDiagnosticsError(null);
    try {
      const res = await TauriClient.runFirstLaunchDiagnostics();
      setDiagnostics(res);
    } catch (err: any) {
      console.error('Failed to run diagnostics:', err);
      setDiagnosticsError(err?.message || 'Failed to execute hardware preflight diagnostics.');
    } finally {
      setDiagnosticsLoading(false);
    }
  };

  useEffect(() => {
    if (currentStep === 2 && !diagnostics) {
      runDiagnostics();
    }
  }, [currentStep]);

  const handleFinishSetup = async () => {
    setSubmitting(true);
    setSubmitError(null);
    try {
      const request: FirstLaunchSetupRequest = {
        workspace_root: workspaceRoot.trim(),
        model_profile: modelProfile,
        kv_cache_dtype: kvCacheDtype,
        context_length: contextLength,
        enable_gaming_mode: enableGamingMode,
      };

      const response = await TauriClient.completeFirstLaunch(request);
      if (response.success) {
        onComplete(response);
      } else {
        setSubmitError(response.message || 'Setup returned failure status.');
      }
    } catch (err: any) {
      console.error('Failed to complete setup:', err);
      setSubmitError(err?.message || 'Failed to complete first-launch setup.');
    } finally {
      setSubmitting(false);
    }
  };

  const steps = [
    { num: 1, title: 'Welcome' },
    { num: 2, title: 'Hardware Preflight' },
    { num: 3, title: 'Workspace Root' },
    { num: 4, title: 'Model & Sidecar' },
    { num: 5, title: 'Confirm & Launch' },
  ];

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 9999,
        background: 'rgba(17, 17, 27, 0.94)',
        backdropFilter: 'blur(8px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontFamily: 'Segoe UI, system-ui, sans-serif',
        color: '#cdd6f4',
      }}
    >
      <div
        style={{
          width: '760px',
          maxHeight: '90vh',
          background: '#181825',
          border: '1px solid #313244',
          borderRadius: '12px',
          boxShadow: '0 24px 64px rgba(0, 0, 0, 0.65)',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
        }}
      >
        {/* Wizard Header */}
        <div
          style={{
            padding: '18px 24px',
            background: '#11111b',
            borderBottom: '1px solid #313244',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <span
              style={{
                width: '10px',
                height: '10px',
                borderRadius: '50%',
                background: '#89b4fa',
                boxShadow: '0 0 10px #89b4fa',
              }}
            />
            <span style={{ fontWeight: 800, fontSize: '15px', letterSpacing: '0.5px', color: '#89b4fa' }}>
              PROJECT FRIDAY
            </span>
            <span style={{ color: '#6c7086' }}>/</span>
            <span style={{ color: '#a6adc8', fontSize: '13px' }}>
              {isInitialSetup ? 'First-Launch Setup Wizard' : 'Diagnostics & Configuration'}
            </span>
          </div>

          {onCancel && (
            <button
              onClick={onCancel}
              style={{
                background: 'transparent',
                border: 'none',
                color: '#6c7086',
                cursor: 'pointer',
                fontSize: '18px',
                lineHeight: 1,
              }}
            >
              ✕
            </button>
          )}
        </div>

        {/* Wizard Steps Bar */}
        <div
          style={{
            display: 'flex',
            background: '#181825',
            borderBottom: '1px solid #313244',
            padding: '12px 24px',
            gap: '8px',
            justifyContent: 'space-between',
          }}
        >
          {steps.map((s) => {
            const isActive = currentStep === s.num;
            const isCompleted = currentStep > s.num;
            return (
              <div
                key={s.num}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  opacity: isActive || isCompleted ? 1 : 0.5,
                  fontSize: '12px',
                }}
              >
                <div
                  style={{
                    width: '22px',
                    height: '22px',
                    borderRadius: '50%',
                    background: isCompleted ? '#a6e3a1' : isActive ? '#89b4fa' : '#313244',
                    color: isCompleted || isActive ? '#11111b' : '#cdd6f4',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontWeight: 700,
                    fontSize: '11px',
                  }}
                >
                  {isCompleted ? '✓' : s.num}
                </div>
                <span
                  style={{
                    color: isActive ? '#89b4fa' : isCompleted ? '#a6e3a1' : '#6c7086',
                    fontWeight: isActive ? 600 : 400,
                  }}
                >
                  {s.title}
                </span>
              </div>
            );
          })}
        </div>

        {/* Wizard Content Body */}
        <div
          style={{
            padding: '24px',
            overflowY: 'auto',
            flex: 1,
            maxHeight: 'calc(90vh - 160px)',
          }}
        >
          {/* STEP 1: WELCOME & SOVEREIGN INVARIANTS */}
          {currentStep === 1 && (
            <div>
              <h2 style={{ margin: '0 0 10px 0', fontSize: '20px', color: '#cdd6f4' }}>
                Welcome to Sovereign Local Agent Computing
              </h2>
              <p style={{ color: '#a6adc8', fontSize: '13px', lineHeight: '1.6', margin: '0 0 20px 0' }}>
                Project Friday transforms your <strong>NVIDIA GeForce RTX 5090 (32 GB GDDR7)</strong> workstation
                into an autonomous, defense-in-depth desktop AI operating system. Everything runs 100% locally on
                loopback with zero telemetry or cloud model leaks.
              </p>

              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: '1fr 1fr',
                  gap: '14px',
                  marginBottom: '20px',
                }}
              >
                <div
                  style={{
                    background: '#1e1e2e',
                    border: '1px solid #313244',
                    borderRadius: '8px',
                    padding: '14px',
                  }}
                >
                  <div style={{ color: '#89b4fa', fontWeight: 600, fontSize: '13px', marginBottom: '4px' }}>
                    ⚡ RTX 5090 Blackwell & EXL3
                  </div>
                  <div style={{ color: '#a6adc8', fontSize: '12px', lineHeight: '1.4' }}>
                    Dedicated TabbyAPI sidecar with ExLlamaV3. Rapid inference with Q6 KV cache quantization and
                    sub-2-second Gaming Mode VRAM evacuation.
                  </div>
                </div>

                <div
                  style={{
                    background: '#1e1e2e',
                    border: '1px solid #313244',
                    borderRadius: '8px',
                    padding: '14px',
                  }}
                >
                  <div style={{ color: '#a6e3a1', fontWeight: 600, fontSize: '13px', marginBottom: '4px' }}>
                    🛡️ Windows Job Object Containment
                  </div>
                  <div style={{ color: '#a6adc8', fontSize: '12px', lineHeight: '1.4' }}>
                    All Python Core and Tabby child processes run enclosed in a kernel Job Object with{' '}
                    <code>KILL_ON_JOB_CLOSE</code>. Zero zombie processes guaranteed.
                  </div>
                </div>

                <div
                  style={{
                    background: '#1e1e2e',
                    border: '1px solid #313244',
                    borderRadius: '8px',
                    padding: '14px',
                  }}
                >
                  <div style={{ color: '#f9e2af', fontWeight: 600, fontSize: '13px', marginBottom: '4px' }}>
                    🔐 Zero-Trust IPC Boundary
                  </div>
                  <div style={{ color: '#a6adc8', fontSize: '12px', lineHeight: '1.4' }}>
                    The desktop WebView holds zero credentials and cannot make HTTP calls. Rust holds bearer
                    tokens, checks NTFS paths, and gates high-risk tools with Win32 modals.
                  </div>
                </div>

                <div
                  style={{
                    background: '#1e1e2e',
                    border: '1px solid #313244',
                    borderRadius: '8px',
                    padding: '14px',
                  }}
                >
                  <div style={{ color: '#cba6f7', fontWeight: 600, fontSize: '13px', marginBottom: '4px' }}>
                    📂 Sovereign Storage & Memory
                  </div>
                  <div style={{ color: '#a6adc8', fontSize: '12px', lineHeight: '1.4' }}>
                    SQLite WAL with FTS5 search. Skills, episodic memory, and scheduled automations persist strictly
                    inside your local workspace root.
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* STEP 2: HARDWARE & ENVIRONMENT PREFLIGHT */}
          {currentStep === 2 && (
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
                <div>
                  <h2 style={{ margin: '0 0 4px 0', fontSize: '18px', color: '#cdd6f4' }}>
                    Hardware & System Preflight Check
                  </h2>
                  <p style={{ margin: 0, color: '#a6adc8', fontSize: '12px' }}>
                    Validating RTX 5090 Blackwell qualification, Windows kernel isolation, and storage permissions.
                  </p>
                </div>
                <button
                  onClick={runDiagnostics}
                  disabled={diagnosticsLoading}
                  style={{
                    background: '#313244',
                    border: '1px solid #45475a',
                    color: '#cdd6f4',
                    padding: '6px 12px',
                    borderRadius: '6px',
                    fontSize: '11px',
                    cursor: diagnosticsLoading ? 'wait' : 'pointer',
                  }}
                >
                  {diagnosticsLoading ? 'Running...' : '↻ Re-run Preflight'}
                </button>
              </div>

              {diagnosticsLoading && (
                <div style={{ padding: '32px', textAlign: 'center', color: '#89b4fa' }}>
                  <div style={{ fontSize: '24px', marginBottom: '8px' }}>⏳</div>
                  <div style={{ fontSize: '13px' }}>Executing kernel and hardware diagnostic tests...</div>
                </div>
              )}

              {diagnosticsError && (
                <div
                  style={{
                    background: 'rgba(243, 139, 168, 0.15)',
                    border: '1px solid #f38ba8',
                    color: '#f38ba8',
                    padding: '12px',
                    borderRadius: '6px',
                    fontSize: '12px',
                    marginBottom: '16px',
                  }}
                >
                  {diagnosticsError}
                </div>
              )}

              {diagnostics && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  {diagnostics.checks.map((chk) => {
                    const isPass = chk.status === 'pass';
                    const isWarn = chk.status === 'warn';
                    return (
                      <div
                        key={chk.id}
                        style={{
                          background: '#1e1e2e',
                          border: `1px solid ${isPass ? '#313244' : isWarn ? '#f9e2af' : '#f38ba8'}`,
                          borderRadius: '8px',
                          padding: '12px 16px',
                          display: 'flex',
                          alignItems: 'flex-start',
                          gap: '12px',
                        }}
                      >
                        <div
                          style={{
                            width: '20px',
                            height: '20px',
                            borderRadius: '50%',
                            background: isPass ? '#a6e3a1' : isWarn ? '#f9e2af' : '#f38ba8',
                            color: '#11111b',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            fontWeight: 800,
                            fontSize: '12px',
                            flexShrink: 0,
                            marginTop: '2px',
                          }}
                        >
                          {isPass ? '✓' : isWarn ? '!' : '✕'}
                        </div>
                        <div style={{ flex: 1 }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <span style={{ fontWeight: 600, fontSize: '13px', color: '#cdd6f4' }}>
                              {chk.name}
                            </span>
                            <span
                              style={{
                                fontSize: '10px',
                                textTransform: 'uppercase',
                                fontWeight: 700,
                                padding: '2px 6px',
                                borderRadius: '4px',
                                background: isPass ? 'rgba(166, 227, 161, 0.15)' : isWarn ? 'rgba(249, 226, 175, 0.15)' : 'rgba(243, 139, 168, 0.15)',
                                color: isPass ? '#a6e3a1' : isWarn ? '#f9e2af' : '#f38ba8',
                              }}
                            >
                              {chk.status}
                            </span>
                          </div>
                          <div style={{ color: '#a6adc8', fontSize: '12px', marginTop: '4px', lineHeight: '1.4' }}>
                            {chk.details}
                          </div>
                          {chk.recommended_action && (
                            <div style={{ color: '#fab387', fontSize: '11px', marginTop: '4px' }}>
                              Tip: {chk.recommended_action}
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {/* STEP 3: WORKSPACE ROOT STORAGE */}
          {currentStep === 3 && (
            <div>
              <h2 style={{ margin: '0 0 6px 0', fontSize: '18px', color: '#cdd6f4' }}>
                Workspace & Storage Directory
              </h2>
              <p style={{ margin: '0 0 16px 0', color: '#a6adc8', fontSize: '12px', lineHeight: '1.5' }}>
                All session state, user-gated skills, episodic memory embeddings, and local configurations
                reside in this canonical directory. Paths are verified via NTFS canonical resolution.
              </p>

              <div style={{ marginBottom: '16px' }}>
                <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '6px', color: '#89b4fa' }}>
                  Workspace Root Path:
                </label>
                <input
                  type="text"
                  value={workspaceRoot}
                  onChange={(e) => setWorkspaceRoot(e.target.value)}
                  placeholder="G:\Project_Ned"
                  style={{
                    width: '100%',
                    background: '#1e1e2e',
                    border: '1px solid #313244',
                    borderRadius: '6px',
                    padding: '10px 14px',
                    color: '#cdd6f4',
                    fontSize: '13px',
                    fontFamily: 'Consolas, monospace',
                    outline: 'none',
                    boxSizing: 'border-box',
                  }}
                />
              </div>

              <div
                style={{
                  background: '#1e1e2e',
                  border: '1px solid #313244',
                  borderRadius: '8px',
                  padding: '14px',
                }}
              >
                <div style={{ fontSize: '12px', fontWeight: 600, color: '#cdd6f4', marginBottom: '8px' }}>
                  Automatic Directory Scaffolding:
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '12px', color: '#a6adc8', fontFamily: 'Consolas, monospace' }}>
                  <div>📁 <code>{workspaceRoot}\.agents\skills\</code> — Inert, user-gated skill files</div>
                  <div>📁 <code>{workspaceRoot}\.agents\memory\</code> — 4-tier memory persistence & FTS5 index</div>
                  <div>📁 <code>{workspaceRoot}\storage\state.db</code> — SQLite WAL session & turn database</div>
                  <div>📁 <code>{workspaceRoot}\config\friday.toml</code> — Local supervisor configuration</div>
                  <div>📁 <code>{workspaceRoot}\logs\</code> — Structured trace logs</div>
                </div>
              </div>
            </div>
          )}

          {/* STEP 4: MODEL PROFILE & INFERENCE SIDECAR */}
          {currentStep === 4 && (
            <div>
              <h2 style={{ margin: '0 0 6px 0', fontSize: '18px', color: '#cdd6f4' }}>
                Model Profile & Inference Sidecar
              </h2>
              <p style={{ margin: '0 0 16px 0', color: '#a6adc8', fontSize: '12px' }}>
                Configure the local ExLlamaV3 / TabbyAPI inference sidecar optimized for RTX 5090 32 GB.
              </p>

              <div style={{ marginBottom: '16px' }}>
                <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '8px', color: '#89b4fa' }}>
                  Default Local Model:
                </label>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {[
                    {
                      id: 'Mistral-Small-3.1-24B-Instruct-2503-exl3',
                      name: 'Mistral Small 3.1 24B Instruct (EXL3)',
                      desc: '24B parameters (~18.5 GB VRAM). Optimal balance of reasoning, tool use, and speed.',
                      recommended: true,
                    },
                    {
                      id: 'Qwen3.5-27B-EXL3',
                      name: 'Qwen3.5-27B (EXL3)',
                      desc: '27B parameters (~20.5 GB VRAM). Advanced multi-step planning and deep reasoning.',
                      recommended: false,
                    },
                    {
                      id: 'Qwen3-Coder-30B-A3B-EXL3',
                      name: 'Qwen3-Coder-30B-A3B (EXL3)',
                      desc: '30B parameters (~22.0 GB VRAM). Dedicated code generation and PowerShell AST verification.',
                      recommended: false,
                    },
                  ].map((m) => (
                    <div
                      key={m.id}
                      onClick={() => setModelProfile(m.id)}
                      style={{
                        padding: '12px 14px',
                        borderRadius: '8px',
                        background: modelProfile === m.id ? 'rgba(137, 180, 250, 0.12)' : '#1e1e2e',
                        border: `1px solid ${modelProfile === m.id ? '#89b4fa' : '#313244'}`,
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                      }}
                    >
                      <div>
                        <div style={{ fontWeight: 600, fontSize: '13px', color: '#cdd6f4' }}>
                          {m.name} {m.recommended && <span style={{ color: '#a6e3a1', fontSize: '11px' }}>(Recommended)</span>}
                        </div>
                        <div style={{ fontSize: '11px', color: '#a6adc8', marginTop: '2px' }}>
                          {m.desc}
                        </div>
                      </div>
                      <input
                        type="radio"
                        checked={modelProfile === m.id}
                        onChange={() => setModelProfile(m.id)}
                        style={{ cursor: 'pointer' }}
                      />
                    </div>
                  ))}
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px', marginBottom: '16px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '6px', color: '#89b4fa' }}>
                    KV Cache Quantization:
                  </label>
                  <select
                    value={kvCacheDtype}
                    onChange={(e) => setKvCacheDtype(e.target.value as any)}
                    style={{
                      width: '100%',
                      background: '#1e1e2e',
                      border: '1px solid #313244',
                      borderRadius: '6px',
                      padding: '8px 12px',
                      color: '#cdd6f4',
                      fontSize: '12px',
                      outline: 'none',
                    }}
                  >
                    <option value="q6">Q6 Cache (~1.2 GB @ 32K context - Recommended)</option>
                    <option value="q8">Q8 Cache (~1.6 GB @ 32K context)</option>
                    <option value="fp16">FP16 Unquantized (~3.2 GB @ 32K context)</option>
                  </select>
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '6px', color: '#89b4fa' }}>
                    Default Context Budget:
                  </label>
                  <select
                    value={contextLength}
                    onChange={(e) => setContextLength(Number(e.target.value))}
                    style={{
                      width: '100%',
                      background: '#1e1e2e',
                      border: '1px solid #313244',
                      borderRadius: '6px',
                      padding: '8px 12px',
                      color: '#cdd6f4',
                      fontSize: '12px',
                      outline: 'none',
                    }}
                  >
                    <option value={16384}>16,384 tokens (Fast)</option>
                    <option value={32768}>32,768 tokens (Default)</option>
                    <option value={65536}>65,536 tokens (Extended)</option>
                  </select>
                </div>
              </div>

              <div
                style={{
                  background: '#1e1e2e',
                  border: '1px solid #313244',
                  borderRadius: '8px',
                  padding: '12px 16px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                }}
              >
                <div>
                  <div style={{ fontWeight: 600, fontSize: '12px', color: '#cdd6f4' }}>
                    Enable Gaming Mode Instant VRAM Evacuation
                  </div>
                  <div style={{ fontSize: '11px', color: '#a6adc8', marginTop: '2px' }}>
                    One-click VRAM release (&lt;2.0s) so games run with 100% GPU memory when needed.
                  </div>
                </div>
                <input
                  type="checkbox"
                  checked={enableGamingMode}
                  onChange={(e) => setEnableGamingMode(e.target.checked)}
                  style={{ width: '18px', height: '18px', cursor: 'pointer' }}
                />
              </div>
            </div>
          )}

          {/* STEP 5: CONFIRMATION & LAUNCH */}
          {currentStep === 5 && (
            <div>
              <h2 style={{ margin: '0 0 6px 0', fontSize: '18px', color: '#cdd6f4' }}>
                Review Configuration & Sovereign Launch
              </h2>
              <p style={{ margin: '0 0 16px 0', color: '#a6adc8', fontSize: '12px' }}>
                Please confirm your setup details below. Clicking launch will generate the configuration,
                scaffold local directories, and start the Project Friday supervisor.
              </p>

              <div
                style={{
                  background: '#1e1e2e',
                  border: '1px solid #313244',
                  borderRadius: '8px',
                  padding: '16px',
                  marginBottom: '16px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '10px',
                  fontSize: '13px',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: '#a6adc8' }}>Workstation GPU:</span>
                  <strong style={{ color: '#a6e3a1' }}>NVIDIA GeForce RTX 5090 (32 GB GDDR7)</strong>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: '#a6adc8' }}>Process Isolation:</span>
                  <strong style={{ color: '#89b4fa' }}>Windows Job Object (Kill-on-Close)</strong>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: '#a6adc8' }}>Workspace Root:</span>
                  <code style={{ color: '#f9e2af' }}>{workspaceRoot}</code>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: '#a6adc8' }}>Primary Model:</span>
                  <strong style={{ color: '#cdd6f4' }}>{modelProfile}</strong>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: '#a6adc8' }}>KV Cache Quantization:</span>
                  <strong style={{ color: '#cba6f7' }}>{kvCacheDtype.toUpperCase()} Cache ({contextLength.toLocaleString()} tokens)</strong>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: '#a6adc8' }}>Gaming Mode Support:</span>
                  <strong style={{ color: enableGamingMode ? '#a6e3a1' : '#6c7086' }}>
                    {enableGamingMode ? 'Enabled (<2s evacuation)' : 'Disabled'}
                  </strong>
                </div>
              </div>

              {submitError && (
                <div
                  style={{
                    background: 'rgba(243, 139, 168, 0.15)',
                    border: '1px solid #f38ba8',
                    color: '#f38ba8',
                    padding: '12px',
                    borderRadius: '6px',
                    fontSize: '12px',
                    marginBottom: '16px',
                  }}
                >
                  {submitError}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Wizard Footer Controls */}
        <div
          style={{
            padding: '16px 24px',
            background: '#11111b',
            borderTop: '1px solid #313244',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <div>
            {currentStep > 1 && (
              <button
                onClick={() => setCurrentStep((prev) => prev - 1)}
                disabled={submitting}
                style={{
                  background: '#313244',
                  border: '1px solid #45475a',
                  color: '#cdd6f4',
                  borderRadius: '6px',
                  padding: '8px 16px',
                  fontSize: '12px',
                  fontWeight: 600,
                  cursor: submitting ? 'not-allowed' : 'pointer',
                }}
              >
                Back
              </button>
            )}
          </div>

          <div style={{ display: 'flex', gap: '10px' }}>
            {currentStep < 5 ? (
              <button
                onClick={() => setCurrentStep((prev) => prev + 1)}
                style={{
                  background: '#89b4fa',
                  border: 'none',
                  color: '#11111b',
                  borderRadius: '6px',
                  padding: '8px 20px',
                  fontSize: '12px',
                  fontWeight: 700,
                  cursor: 'pointer',
                }}
              >
                Continue →
              </button>
            ) : (
              <button
                onClick={handleFinishSetup}
                disabled={submitting}
                style={{
                  background: submitting ? '#45475a' : '#a6e3a1',
                  border: 'none',
                  color: '#11111b',
                  borderRadius: '6px',
                  padding: '8px 24px',
                  fontSize: '13px',
                  fontWeight: 800,
                  cursor: submitting ? 'wait' : 'pointer',
                }}
              >
                {submitting ? 'Initializing Workspace...' : '✓ Complete Setup & Launch'}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
