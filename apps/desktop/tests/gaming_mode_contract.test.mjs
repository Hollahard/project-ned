import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRoot = path.resolve(__dirname, '..', '..', '..');

test('Phase 5 API schema contracts exist and define telemetry and gaming mode', () => {
  const apiSchemaPath = path.join(projectRoot, 'contracts', 'api.schema.json');
  assert.ok(fs.existsSync(apiSchemaPath), 'api.schema.json must exist');

  const schema = JSON.parse(fs.readFileSync(apiSchemaPath, 'utf8'));
  const defs = schema.definitions;

  assert.ok(defs.GpuTelemetryResponse, 'GpuTelemetryResponse schema definition must exist');
  assert.ok(defs.PreflightRequest, 'PreflightRequest schema definition must exist');
  assert.ok(defs.PreflightResponse, 'PreflightResponse schema definition must exist');
  assert.ok(defs.GamingModeStatusResponse, 'GamingModeStatusResponse schema definition must exist');

  // Verify key fields in GamingModeStatusResponse
  assert.ok(defs.GamingModeStatusResponse.required.includes('active'));
  assert.ok(defs.GamingModeStatusResponse.required.includes('elapsed_seconds'));
  assert.ok(defs.GamingModeStatusResponse.required.includes('vram_freed_mb'));

  // Verify key fields in PreflightResponse
  assert.ok(defs.PreflightResponse.required.includes('fits'));
  assert.ok(defs.PreflightResponse.required.includes('estimated_total_mb'));
  assert.ok(defs.PreflightResponse.required.includes('available_vram_mb'));
});

test('TauriClient service defines all Phase 5 IPC invocations', () => {
  const clientPath = path.join(projectRoot, 'apps', 'desktop', 'src', 'services', 'tauriClient.ts');
  assert.ok(fs.existsSync(clientPath), 'tauriClient.ts must exist');

  const content = fs.readFileSync(clientPath, 'utf8');
  assert.ok(content.includes('getGpuTelemetry'), 'TauriClient must define getGpuTelemetry');
  assert.ok(content.includes('checkVramPreflight'), 'TauriClient must define checkVramPreflight');
  assert.ok(content.includes('activateGamingMode'), 'TauriClient must define activateGamingMode');
  assert.ok(content.includes('deactivateGamingMode'), 'TauriClient must define deactivateGamingMode');
  assert.ok(content.includes('getGamingModeStatus'), 'TauriClient must define getGamingModeStatus');
});

test('Rust supervisor exports Phase 5 commands in invoke_handler', () => {
  const libPath = path.join(projectRoot, 'apps', 'desktop', 'src-tauri', 'src', 'lib.rs');
  assert.ok(fs.existsSync(libPath), 'lib.rs must exist');

  const content = fs.readFileSync(libPath, 'utf8');
  assert.ok(content.includes('commands::get_gpu_telemetry'), 'invoke_handler must register get_gpu_telemetry');
  assert.ok(content.includes('commands::check_vram_preflight'), 'invoke_handler must register check_vram_preflight');
  assert.ok(content.includes('commands::activate_gaming_mode'), 'invoke_handler must register activate_gaming_mode');
  assert.ok(content.includes('commands::deactivate_gaming_mode'), 'invoke_handler must register deactivate_gaming_mode');
});
