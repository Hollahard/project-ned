// Imported by binding-proof.js only in a binding-fixture build. All file writes
// happen in the native helper using fixed filenames under an explicit temp root.
export async function runPreviewWatchProof() {
  const checks = [];
  const assert = (value, label) => { if (!value) throw new Error(label); checks.push(label); };
  const invoke = window.__TAURI__.core.invoke;
  const transport = window.__HERMES_NATIVE_TRANSPORT__;
  const phase = name => invoke('hermes_binding_fixture', { phase: name });
  const request = (method, arg) => transport.invoke('hermes_host_request', { method, args: [arg] });
  const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
  const events = [];
  let faulted = false;
  const off = await transport.subscribe('hermes:host:event', event => {
    if (event.name === 'preview-file-changed') events.push(event.payload);
    if (event.name === 'preview-watch-failed') faulted = true;
  });
  const wait = async predicate => {
    const deadline = Date.now() + 5000;
    while (!predicate()) {
      if (Date.now() > deadline || faulted) throw new Error('native preview event deadline/fault');
      await delay(25);
    }
  };
  try {
    await phase('preview-observer-create');
    let observer = await phase('preview-observer-stats');
    const observerDeadline = Date.now() + 5000;
    while (!observer.ready) {
      if (Date.now() > observerDeadline) throw new Error('preview observer failed to initialize');
      await delay(50);
      observer = await phase('preview-observer-stats');
    }
    assert(observer.count === 0, 'preview-adversarial-any-listener-ready');
    await phase('event');
    while (observer.controls !== 1) {
      if (Date.now() > observerDeadline) throw new Error('preview observer missed positive broadcast control');
      await delay(50);
      observer = await phase('preview-observer-stats');
    }
    assert(observer.controls === 1, 'preview-adversarial-any-listener-positive-control');
    const prepared = await phase('preview-prepare');
    const file = await request('watchPreviewFile', prepared.url);
    const directory = await request('watchDirectory', prepared.directory);
    assert(typeof file.id === 'string' && file.path === prepared.path, 'preview-file-watch-real-receipt');
    assert(typeof directory.id === 'string' && directory.id !== file.id, 'preview-directory-watch-real-receipt');
    assert(events.length === 0, 'preview-registration-does-not-fabricate-change');
    await phase('preview-write');
    await wait(() => events.some(event => event.id === file.id));
    const event = events.find(event => event.id === file.id);
    assert(event.path === file.path && event.url === prepared.url && Object.keys(event).sort().join(',') === 'id,path,url', 'preview-real-native-file-change-payload');
    // The directory fixture is separate from the file, but use an explicit
    // pre-mutation event baseline so an older invalidation cannot satisfy this.
    const directoryBefore = events.filter(event => event.id === directory.id).length;
    await phase('preview-directory-write');
    await wait(() => events.filter(event => event.id === directory.id).length > directoryBefore);
    assert(events.find(event => event.id === directory.id).path === prepared.directory, 'preview-real-native-directory-change-payload');
    assert(await request('stopPreviewFileWatch', file.id) === true, 'preview-native-stop-owned-watch');
    assert(await request('stopPreviewFileWatch', file.id) === false, 'preview-native-stop-idempotent');
    assert(await request('stopPreviewFileWatch', directory.id) === true, 'preview-native-stop-directory');
    // Stop fences native enqueueing. Already enqueued JS delivery is separate;
    // let it settle before measuring the following, genuinely new file write.
    await delay(400);
    const before = await phase('preview-stats');
    const eventCount = events.length;
    await phase('preview-write');
    await delay(800);
    const after = await phase('preview-stats');
    assert(after.watchCount === 0 && after.dispatched === before.dispatched && events.length === eventCount, 'preview-stop-prevents-late-native-dispatch');
    assert(after.faults === 0 && !faulted, 'preview-no-hidden-native-watch-faults');
    observer = await phase('preview-observer-stats');
    assert(observer.ready && observer.count === 0, 'preview-native-events-do-not-reach-other-window-any-listener');
    await phase('preview-observer-close');
    await request('watchPreviewFile', prepared.path);
    await phase('preview-retire');
    let retired = false;
    try { await request('watchPreviewFile', prepared.path); }
    catch (error) { retired = error.code === 'HERMES_PREVIEW_OWNER_RETIRED'; }
    assert(retired, 'preview-native-owner-retirement-permanent');
    return checks;
  } finally { off(); }
}
