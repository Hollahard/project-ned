// Deliberately subscribes with the global ANY target. Tauri emit_to does not
// isolate this listener; the bound owner eval route must keep the count at zero.
let observed = 0;
let controls = 0;
await window.__TAURI__.event.listen('hermes:host:event', event => {
  if (event.payload?.name === 'preview-file-changed' || event.payload?.name === 'preview-watch-failed') {
    observed++;
  }
  if (event.payload?.name === 'boot-progress' && event.payload?.payload?.stage === 'binding-fixture') controls++;
  location.hash = `ready-${observed}-${controls}`;
});
location.hash = 'ready-0-0';
