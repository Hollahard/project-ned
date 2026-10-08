// Two phases in the SAME native WebView. Only this disposable fixture profile
// uses sessionStorage to continue the proof after a real document reload.
const key = 'hermes.native.preview.reload.proof';
const saved = sessionStorage.getItem(key);
const checks = saved ? JSON.parse(saved).checks : [];
const assert = (value, label) => { if (!value) throw new Error(label); checks.push(label); };
const phase = name => window.__TAURI__.core.invoke('hermes_binding_fixture', { phase: name });
const request = (method, path) => window.__HERMES_NATIVE_TRANSPORT__.invoke('hermes_host_request', { method, args: [path] });
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const events = [];
const off = await window.__HERMES_NATIVE_TRANSPORT__.subscribe('hermes:host:event', event => {
  if (event.name === 'preview-file-changed') events.push(event.payload);
});
const wait = async predicate => {
  const deadline = Date.now() + 5000;
  while (!predicate()) {
    if (Date.now() > deadline) throw new Error('native reload fixture event deadline');
    await delay(25);
  }
};

if (!saved) {
  const prepared = await phase('preview-prepare');
  const watch = await request('watchPreviewFile', prepared.url);
  await phase('preview-write');
  await wait(() => events.some(event => event.id === watch.id));
  assert(events[0].path === prepared.path, 'preview-reload-real-file-event-before-navigation');
  location.hash = '/preview-hash-route';
  await delay(100);
  const stats = await phase('preview-stats');
  assert(stats.watchCount === 1, 'preview-hash-navigation-preserves-owner');
  const before = events.length;
  await phase('preview-write');
  await wait(() => events.length > before);
  assert(events.at(-1).id === watch.id, 'preview-hash-route-still-receives-real-changes');
  sessionStorage.setItem(key, JSON.stringify({ checks, path: prepared.path }));
  location.reload();
} else {
  const marker = JSON.parse(saved);
  const stats = await phase('preview-retired-stats');
  assert(stats.retired && stats.watchCount === 0, 'preview-document-reload-retires-same-native-owner');
  let retired = false;
  try { await request('watchPreviewFile', marker.path); }
  catch (error) { retired = error.code === 'HERMES_PREVIEW_OWNER_RETIRED'; }
  assert(retired, 'preview-reloaded-document-cannot-reuse-old-native-owner');
  // Native replay uses the actual previously observed file event and its old
  // document id. This intentionally models a queued eval reaching the new page.
  await phase('preview-replay-stale');
  await delay(600);
  assert(events.length === 0, 'preview-new-document-rejects-old-native-queued-envelope');
  sessionStorage.removeItem(key);
  off();
  await window.__TAURI__.core.invoke('hermes_binding_fixture', { phase: 'finish', checks });
}
