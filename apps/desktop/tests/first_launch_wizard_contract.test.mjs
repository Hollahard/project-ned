import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRoot = path.resolve(__dirname, '..', '..', '..');

test('Phase 15: Tauri 2 packaging and Windows installer bundle configuration', () => {
  const confPath = path.join(projectRoot, 'apps', 'desktop', 'src-tauri', 'tauri.conf.json');
  assert.ok(fs.existsSync(confPath), 'tauri.conf.json must exist');

  const conf = JSON.parse(fs.readFileSync(confPath, 'utf8'));

  // Bundle active and targets
  assert.strictEqual(conf.bundle.active, true, 'Bundle must be active');
  assert.ok(Array.isArray(conf.bundle.targets), 'Bundle targets must be an array');
  assert.ok(
    conf.bundle.targets.includes('nsis') || conf.bundle.targets.includes('all'),
    'Bundle targets must include NSIS Windows installer'
  );

  // Icons configured
  assert.ok(Array.isArray(conf.bundle.icon) && conf.bundle.icon.length > 0, 'Bundle must define icons');
  for (const iconRelPath of conf.bundle.icon) {
    const iconAbsPath = path.join(projectRoot, 'apps', 'desktop', 'src-tauri', iconRelPath);
    assert.ok(fs.existsSync(iconAbsPath), `Icon file ${iconRelPath} must exist`);
  }

  // Windows NSIS settings
  assert.ok(conf.bundle.windows?.nsis, 'NSIS configuration must exist');
  assert.strictEqual(conf.bundle.windows.nsis.installMode, 'currentUser');
  assert.ok(conf.bundle.publisher, 'Publisher must be specified');
  assert.ok(conf.bundle.shortDescription, 'Short description must be specified');
});

test('Phase 15: Contract schemas exist and define First-Launch Wizard IPC endpoints', () => {
  const apiSchemaPath = path.join(projectRoot, 'contracts', 'api.schema.json');
  assert.ok(fs.existsSync(apiSchemaPath), 'api.schema.json must exist');

  const schema = JSON.parse(fs.readFileSync(apiSchemaPath, 'utf8'));
  const defs = schema.definitions;

  assert.ok(defs.FirstLaunchStatusResponse, 'FirstLaunchStatusResponse schema definition must exist');
  assert.ok(defs.FirstLaunchDiagnosticItem, 'FirstLaunchDiagnosticItem schema definition must exist');
  assert.ok(defs.FirstLaunchDiagnosticsResponse, 'FirstLaunchDiagnosticsResponse schema definition must exist');
  assert.ok(defs.FirstLaunchSetupRequest, 'FirstLaunchSetupRequest schema definition must exist');
  assert.ok(defs.FirstLaunchSetupResponse, 'FirstLaunchSetupResponse schema definition must exist');

  // Verify key fields in FirstLaunchDiagnosticsResponse
  assert.ok(defs.FirstLaunchDiagnosticsResponse.required.includes('overall_status'));
  assert.ok(defs.FirstLaunchDiagnosticsResponse.required.includes('gpu_detected'));
  assert.ok(defs.FirstLaunchDiagnosticsResponse.required.includes('job_object_supported'));
  assert.ok(defs.FirstLaunchDiagnosticsResponse.required.includes('checks'));

  // Verify key fields in FirstLaunchSetupRequest
  assert.ok(defs.FirstLaunchSetupRequest.required.includes('workspace_root'));
  assert.ok(defs.FirstLaunchSetupRequest.required.includes('model_profile'));
  assert.ok(defs.FirstLaunchSetupRequest.required.includes('kv_cache_dtype'));
  assert.ok(defs.FirstLaunchSetupRequest.required.includes('context_length'));
});

test('Phase 15: TauriClient defines first-launch IPC methods with mock fallbacks', () => {
  const clientPath = path.join(projectRoot, 'apps', 'desktop', 'src', 'services', 'tauriClient.ts');
  assert.ok(fs.existsSync(clientPath), 'tauriClient.ts must exist');

  const content = fs.readFileSync(clientPath, 'utf8');
  assert.ok(content.includes('checkFirstLaunch'), 'TauriClient must define checkFirstLaunch');
  assert.ok(content.includes('runFirstLaunchDiagnostics'), 'TauriClient must define runFirstLaunchDiagnostics');
  assert.ok(content.includes('completeFirstLaunch'), 'TauriClient must define completeFirstLaunch');
});

test('Phase 15: Rust supervisor exports First-Launch commands in invoke_handler', () => {
  const libPath = path.join(projectRoot, 'apps', 'desktop', 'src-tauri', 'src', 'lib.rs');
  assert.ok(fs.existsSync(libPath), 'lib.rs must exist');

  const content = fs.readFileSync(libPath, 'utf8');
  assert.ok(content.includes('pub mod first_launch'), 'lib.rs must declare pub mod first_launch');
  assert.ok(content.includes('commands::check_first_launch'), 'invoke_handler must register check_first_launch');
  assert.ok(content.includes('commands::run_first_launch_diagnostics'), 'invoke_handler must register run_first_launch_diagnostics');
  assert.ok(content.includes('commands::complete_first_launch'), 'invoke_handler must register complete_first_launch');
});

test('Phase 15: FirstLaunchWizard React 19 component exists and integrates in App', () => {
  const wizardPath = path.join(projectRoot, 'apps', 'desktop', 'src', 'components', 'FirstLaunchWizard.tsx');
  assert.ok(fs.existsSync(wizardPath), 'FirstLaunchWizard.tsx must exist');

  const appPath = path.join(projectRoot, 'apps', 'desktop', 'src', 'App.tsx');
  const appContent = fs.readFileSync(appPath, 'utf8');

  assert.ok(appContent.includes('FirstLaunchWizard'), 'App.tsx must import FirstLaunchWizard');
  assert.ok(appContent.includes('checkFirstLaunch'), 'App.tsx must invoke checkFirstLaunch on boot');
  assert.ok(appContent.includes('showWizard'), 'App.tsx must manage wizard visibility state');
});
