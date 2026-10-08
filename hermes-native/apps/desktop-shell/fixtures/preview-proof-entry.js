import { runPreviewWatchProof } from './preview-watch-proof.js';
let checks;
try { checks = await runPreviewWatchProof(); }
catch (error) {
  checks = ['preview-fixture-failed'];
  if (typeof error?.code === 'string' && /^HERMES_[A-Z_]{1,80}$/.test(error.code)) checks.push(error.code);
  if (typeof error?.message === 'string' && /^preview-[a-z-]{1,100}$/.test(error.message)) checks.push(error.message);
}
await window.__TAURI__.core.invoke('hermes_binding_fixture', { phase: 'finish', checks });
