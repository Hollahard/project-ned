const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const vm = require('node:vm');
const { randomUUID } = require('node:crypto');
const test = require('node:test');
const assert = require('node:assert/strict');
const source = readFileSync(join(__dirname, '../src/transport.js'), 'utf8');

// These test only bridge routing/lifetime policy. Real filesystem production
// and native WebView isolation are tested by the separate native fixture.
function page({ local = true, top = true } = {}) {
  const listeners = new Map();
  const state = { calls: [], errors: [], failNext: false, offCount: 0 };
  state.documentId = randomUUID();
  let next = 1;
  const window = {
    __TAURI__: {
      core: { invoke: async (...args) => { state.calls.push(args); return null; } },
      event: {
        listen: async (_, callback) => {
          if (state.failNext) { state.failNext = false; throw Error('fixture listener failure'); }
          const id = next++;
          listeners.set(id, callback);
          return () => { state.offCount++; listeners.delete(id); };
        },
      },
    },
  };
  window.top = top ? window : {};
  const context = vm.createContext({ window, crypto: { randomUUID: () => state.documentId }, location: { protocol: 'http:', host: local ? 'tauri.localhost' : 'other.example' }, console: { error: code => state.errors.push(code) } });
  vm.runInContext(source, context);
  return {
    window, state,
    bridge: window.__HERMES_NATIVE_TRANSPORT__,
    receive: event => window.__HERMES_NATIVE_EVENT_RECEIVER__({ documentId: state.documentId, event }),
    bus: payload => { for (const callback of listeners.values()) callback({ payload }); },
  };
}

const change = { name: 'preview-file-changed', payload: { id: 'preview-1-1', path: 'G:\\fixture.txt', url: 'file:///G:/fixture.txt' } };

test('receiver and transport are installed once and cannot be replaced', () => {
  const p = page();
  assert(Object.isFrozen(p.bridge));
  assert.equal(Object.getOwnPropertyDescriptor(p.window, '__HERMES_NATIVE_EVENT_RECEIVER__').writable, false);
  assert.equal(Object.getOwnPropertyDescriptor(p.window, '__HERMES_NATIVE_EVENT_RECEIVER__').configurable, false);
});

test('local receiver routes preview and fault data to its page only', async () => {
  const a = page();
  const b = page();
  const first = [], second = [];
  await a.bridge.subscribe('hermes:host:event', event => first.push(event));
  await b.bridge.subscribe('hermes:host:event', event => second.push(event));
  a.receive(change);
  a.receive({ name: 'preview-watch-failed', payload: { id: 'preview-1-1', error: 'io' } });
  assert.equal(first.length, 2);
  assert.equal(second.length, 0);
});

test('application event bus cannot deliver preview while retained boot events still work', async () => {
  const p = page();
  const received = [];
  await p.bridge.subscribe('hermes:host:event', event => received.push(event));
  p.bus(change);
  p.bus({ name: 'preview-watch-failed', payload: { id: 'preview-1-1', error: 'io' } });
  p.bus({ name: 'boot-progress', payload: { stage: 'fixture' } });
  assert.equal(received.length, 1);
  assert.equal(received[0].name, 'boot-progress');
});

test('duplicate callback subscriptions have independent and idempotent lifetimes', async () => {
  const p = page();
  let count = 0;
  const listener = () => count++;
  const offA = await p.bridge.subscribe('hermes:host:event', listener);
  const offB = await p.bridge.subscribe('hermes:host:event', listener);
  p.receive(change);
  assert.equal(count, 2);
  offA(); offA();
  p.receive(change);
  assert.equal(count, 3);
  offB();
  p.receive(change);
  assert.equal(count, 3);
  assert.equal(p.state.offCount, 2);
});

test('failed native subscription cleans up its local receiver registration', async () => {
  const p = page();
  let count = 0;
  p.state.failNext = true;
  await assert.rejects(p.bridge.subscribe('hermes:host:event', () => count++));
  p.receive(change);
  assert.equal(count, 0);
});

test('receiver rejects unknown names and malformed or oversized payloads', async () => {
  const p = page();
  let count = 0;
  await p.bridge.subscribe('hermes:host:event', () => count++);
  for (const event of [
    { name: 'backend-exit', payload: {} },
    { name: 'preview-file-changed', payload: null },
    { name: 'preview-file-changed', payload: { ...change.payload, id: 'x'.repeat(129) } },
    { name: 'preview-file-changed', payload: { ...change.payload, path: 'x'.repeat(32768) } },
    { name: 'preview-file-changed', payload: { ...change.payload, url: null } },
    { name: 'preview-watch-failed', payload: { id: 'x', error: 'x'.repeat(65) } },
  ]) p.receive(event);
  assert.equal(count, 0);
});

test('control uses the separate native command and host invoke rejects arbitrary commands', async () => {
  const p = page();
  await p.bridge.control('profiles.list', { scope: 'fixture' });
  assert.equal(p.state.calls[0][0], 'hermes_control_request');
  assert.equal(p.state.calls[0][1].operation, 'profiles.list');
  await assert.rejects(p.bridge.invoke('runCommand', {}));
  assert.equal(p.state.calls.length, 1);
});

test('nonlocal pages and iframe contexts receive no transport or receiver', () => {
  for (const options of [{ local: false }, { top: false }]) {
    const p = page(options);
    assert.equal(p.bridge, undefined);
    assert.equal(p.window.__HERMES_NATIVE_EVENT_RECEIVER__, undefined);
  }
});

test('one failing consumer does not suppress other consumers', async () => {
  const p = page();
  let count = 0;
  await p.bridge.subscribe('hermes:host:event', () => { throw Error('consumer failed'); });
  await p.bridge.subscribe('hermes:host:event', () => count++);
  p.receive(change);
  assert.equal(count, 1);
  assert.deepEqual(p.state.errors, ['HERMES_PREVIEW_LISTENER_FAILED']);
});

test('replacement document ignores queued old-document envelopes', async () => {
  const previous = page();
  const replacement = page();
  let count = 0;
  await replacement.bridge.subscribe('hermes:host:event', () => count++);
  replacement.window.__HERMES_NATIVE_EVENT_RECEIVER__({ documentId: previous.state.documentId, event: change });
  replacement.window.__HERMES_NATIVE_EVENT_RECEIVER__({ event: change });
  assert.equal(count, 0);
  replacement.receive(change);
  assert.equal(count, 1);
});

test('host request carries the captured page id and overrides caller-provided routing id', async () => {
  const p = page();
  await p.bridge.invoke('hermes_host_request', { method: 'watchPreviewFile', args: ['G:\\fixture'], documentId: 'caller-selected' });
  assert.equal(p.state.calls[0][1].documentId, p.state.documentId);
});
