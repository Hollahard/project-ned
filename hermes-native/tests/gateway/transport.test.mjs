import assert from 'node:assert/strict';
import test from 'node:test';
import { once } from 'node:events';
import { channel, gateway, manifest } from './upstream.mjs';
import { makeChannel, makeGateway, notify, ready, respondReplay, loopbackFixture } from './fixtures.mjs';

test('baseline is pinned before executing original TypeScript modules', () => {
  assert.equal(manifest.baseline_commit, '649d6c0391029f35959cfbc240eb3534a6667cf5');
  assert.equal(typeof channel.JsonRpcRequestChannel, 'function');
  assert.equal(typeof gateway.JsonRpcGatewayClient, 'function');
});

test('out-of-order results correlate by request id and preserve structured errors', async t => {
  const f = makeChannel(); t.after(() => f.close());
  const first = f.client.request('session.list', { offset: 0 });
  const second = f.client.request('session.history', { session_id: 'missing' });
  const rejected = assert.rejects(second, error => {
    assert.ok(error instanceof channel.JsonRpcGatewayError);
    assert.equal(error.code, -32004);
    assert.deepEqual(error.data, { session_id: 'missing' });
    return true;
  });
  f.inbound({ jsonrpc: '2.0', id: f.sent[1].id, error: { code: -32004, message: 'missing session', data: { session_id: 'missing' } } });
  f.inbound({ jsonrpc: '2.0', id: f.sent[0].id, result: { sessions: [] } });
  assert.deepEqual(await first, { sessions: [] });
  await rejected;
  assert.notEqual(f.sent[0].id, f.sent[1].id);
});

test('notifications decode without a response and unsupported raw frames are ignored', t => {
  const events = [];
  const f = makeChannel({ onEvent: event => events.push(event) }); t.after(() => f.close());
  const event = { type: 'message.delta', session_id: 's1', seq: 3, payload: { delta: 'hello' } };
  const text = JSON.stringify({ jsonrpc: '2.0', method: 'event', params: event });
  assert.equal(channel.wireFrameText(new TextEncoder().encode(text)), text);
  f.client.handleFrame(text);
  for (const invalid of ['not-json', 'null', '2', '"scalar"']) assert.equal(f.client.handleFrame(invalid), null);
  assert.equal(channel.wireFrameText({ data: text }), null);
  assert.deepEqual(events, [event]);
  assert.deepEqual(f.sent, []);
});

test('server requests try handlers in order, reply once per delivery, and fail unsupported methods', t => {
  const f = makeChannel(); t.after(() => f.close());
  let captured;
  f.client.onRequest(() => false);
  const remove = f.client.onRequest(request => { captured = request; });
  f.inbound({ jsonrpc: '2.0', id: 'ask-1', method: 'clarify', params: { session_id: 's1' } });
  captured.respond({ answer: 'yes' });
  captured.respond({ answer: 'duplicate' });
  captured.fail(-32603, 'too late');
  assert.deepEqual(f.sent, [{ jsonrpc: '2.0', id: 'ask-1', result: { answer: 'yes' } }]);
  remove();
  f.inbound({ jsonrpc: '2.0', id: 'ask-2', method: 'unknown.method', params: {} });
  assert.equal(f.sent.at(-1).error.code, -32601);
});

test('a crashing server-request handler answers internal error without breaking later responses', async t => {
  const failures = [];
  const f = makeChannel({ onRequestHandlerError: error => failures.push(error.message) }); t.after(() => f.close());
  f.client.onRequest(() => { throw new Error('fixture handler fault'); });
  f.inbound({ jsonrpc: '2.0', id: 'ask-1', method: 'clarify', params: {} });
  assert.equal(f.sent[0].error.code, -32603);
  const pending = f.client.request('session.list');
  f.inbound({ jsonrpc: '2.0', id: f.sent[1].id, result: [] });
  assert.deepEqual(await pending, []);
  assert.deepEqual(failures, ['fixture handler fault']);
});

test('delayed answers stay with their owner-scoped client after foreground profile changes', async t => {
  const a = makeGateway(); const b = makeGateway();
  t.after(() => { a.client.close(); b.client.close(); });
  const socketA = await a.connect(); const socketB = await b.connect();
  const cards = [];
  a.client.onRequest(request => cards.push({ ...request, owner: 'profile-a' }));
  b.client.onRequest(request => cards.push({ ...request, owner: 'profile-b' }));
  let foreground = a.client;
  socketA.inbound({ jsonrpc: '2.0', id: 'same-request-id', method: 'clarify', params: { session_id: 'session-a' } });
  foreground = b.client;
  socketB.inbound({ jsonrpc: '2.0', id: 'same-request-id', method: 'clarify', params: { session_id: 'session-b' } });
  cards.find(card => card.owner === 'profile-a').respond({ answer: 'late answer for a' });
  assert.equal(foreground, b.client);
  assert.deepEqual(socketA.sent, [{ jsonrpc: '2.0', id: 'same-request-id', result: { answer: 'late answer for a' } }]);
  assert.deepEqual(socketB.sent, []);
  cards.find(card => card.owner === 'profile-b').respond({ answer: 'answer for b' });
  assert.equal(socketB.sent[0].result.answer, 'answer for b');
});

test('ownership caveat: an existing delayed callback uses the channel current transport', t => {
  const f = makeChannel(); t.after(() => f.close());
  let delayed;
  f.client.onRequest(request => { delayed = request; });
  f.inbound({ jsonrpc: '2.0', id: 'ask-owner-a', method: 'clarify', params: {} });
  f.client.detach(new Error('old connection left'));
  const replacement = [];
  f.client.attach({ send(text) { replacement.push(JSON.parse(text)); } });
  delayed.respond({ answer: 'late' });
  assert.deepEqual(f.sent, []);
  assert.equal(replacement[0].id, 'ask-owner-a');
  // Therefore a host must never repurpose one channel across profile/backend owners.
});

test('open requests are replayed before resume resolves; idempotence is scoped to each delivery', async t => {
  const f = makeChannel(); t.after(() => f.close());
  const deliveries = [];
  f.client.onRequest(request => deliveries.push(request));
  const pending = f.client.request('session.resume', { session_id: 's1' });
  f.inbound({ jsonrpc: '2.0', id: f.sent[0].id, result: { open_requests: [{ id: 'open-1', method: 'clarify', params: { session_id: 's1' } }] } });
  assert.equal(deliveries.length, 1);
  assert.equal(deliveries[0].replayed, true);
  await pending;
  f.client.deliverRequest('open-1', 'clarify', { session_id: 's1' }, true);
  deliveries[0].respond({ answer: 'one' });
  deliveries[1].respond({ answer: 'two' });
  assert.equal(f.sent.filter(frame => frame.id === 'open-1').length, 2);
  // Backend correlation/settlement must absorb duplicates across replay deliveries.
});

test('not-shown decline is silent until the backend advertises support', async t => {
  const f = makeChannel(); t.after(() => f.close());
  f.client.onRequest(request => request.decline('not shown'));
  f.inbound({ jsonrpc: '2.0', id: 'legacy-ask', method: 'clarify', params: {} });
  assert.deepEqual(f.sent, []);
  f.inbound({ jsonrpc: '2.0', method: 'event', params: { type: 'gateway.ready', payload: {} } });
  assert.equal(f.sent[0].method, 'client.capabilities');
  f.inbound({ jsonrpc: '2.0', id: f.sent[0].id, result: { declines_not_shown: true } });
  await Promise.resolve();
  f.inbound({ jsonrpc: '2.0', id: 'new-ask', method: 'clarify', params: {} });
  assert.equal(f.sent.at(-1).error.code, 4404);
});

test('AbortSignal rejects only the local call and does not send a server cancellation RPC', async t => {
  const f = makeChannel(); t.after(() => f.close());
  const controller = new AbortController();
  const pending = f.client.request('session.resume', {}, 1000, controller.signal);
  const rejected = assert.rejects(pending, { name: 'AbortError' });
  controller.abort();
  await rejected;
  assert.equal(f.sent.length, 1);
  f.inbound({ jsonrpc: '2.0', id: f.sent[0].id, result: { ignored: true } });
  await assert.rejects(f.client.request('session.resume', {}, 1000, controller.signal), { name: 'AbortError' });
  assert.equal(f.sent.length, 1);
});

test('detach rejects all pending calls and the closed channel cannot send', async () => {
  const f = makeChannel();
  const first = assert.rejects(f.client.request('first'), /fixture disposed/);
  const second = assert.rejects(f.client.request('second'), /fixture disposed/);
  f.close();
  await Promise.all([first, second]);
  assert.equal(f.client.owns(f.transport), false);
  await assert.rejects(f.client.request('third'), /not connected/);
  assert.equal(f.sent.length, 2);
});

test('reconnect replays gaps, holds racing live frames, deduplicates and resolves the session barrier', async t => {
  const f = makeGateway(); t.after(() => f.client.close());
  const events = [];
  f.client.on('message.delta', event => events.push(event));
  const first = await f.connect(); ready(first, 'epoch-a');
  notify(first, 'message.delta', { session_id: 's1', seq: 1 });
  f.client.invalidate('fixture disconnect');
  assert.equal(await f.client.sessionReplayBarrier('s1'), false);
  const second = await f.connect();
  const barrier = f.client.sessionReplayBarrier('s1');
  assert.ok(barrier instanceof Promise);
  notify(second, 'message.delta', { session_id: 's1', seq: 4 });
  assert.deepEqual(events.map(event => event.seq), [1]);
  const request = respondReplay(second, {
    epoch: 'epoch-a', latest_seq: 4, truncated: false,
    events: [2, 3, 4].map(seq => ({ type: 'message.delta', session_id: 's1', seq })),
  });
  assert.deepEqual(request.params, { session_id: 's1', last_seen: 1 });
  assert.equal(await barrier, true);
  assert.deepEqual(events.map(event => event.seq), [1, 2, 3, 4]);
  assert.ok(events.slice(1).every(event => event.replayed && event.replayEpoch === 'epoch-a'));
  assert.deepEqual(f.client.getSeqWatermarks(), { s1: 4 });
});

test('backend epoch change clears old cursors and permits authoritative history recovery', async t => {
  const f = makeGateway(); t.after(() => f.client.close());
  const events = [];
  f.client.on('message.delta', event => events.push(event));
  const first = await f.connect(); ready(first, 'epoch-a');
  notify(first, 'message.delta', { session_id: 's1', seq: 97 });
  f.client.invalidate();
  const second = await f.connect();
  const barrier = f.client.sessionReplayBarrier('s1');
  ready(second, 'epoch-b');
  assert.equal(await barrier, true);
  assert.deepEqual(f.client.getSeqWatermarks(), {});
  respondReplay(second, { epoch: 'epoch-a', events: [{ type: 'message.delta', session_id: 's1', seq: 98 }] });
  await Promise.resolve();
  notify(second, 'message.delta', { session_id: 's1', seq: 1 });
  assert.deepEqual(events.map(event => event.seq), [97, 1]);
  assert.equal(events.at(-1).replayEpoch, 'epoch-b');
});

test('unsupported replay falls back without proving history completeness', async t => {
  const f = makeGateway(); t.after(() => f.client.close());
  const seqs = [];
  f.client.on('message.delta', event => seqs.push(event.seq));
  const first = await f.connect();
  notify(first, 'message.delta', { session_id: 's1', seq: 1 });
  f.client.invalidate();
  const second = await f.connect();
  const barrier = f.client.sessionReplayBarrier('s1');
  notify(second, 'message.delta', { session_id: 's1', seq: 9 });
  const request = second.sent.find(frame => frame.method === 'session.events.since');
  second.inbound({ jsonrpc: '2.0', id: request.id, error: { code: -32601, message: 'unsupported replay' } });
  assert.equal(await barrier, true);
  assert.deepEqual(seqs, [1, 9]);
});

test('ordinary live duplicate notifications dispatch twice while the watermark stays monotonic', async t => {
  const f = makeGateway(); t.after(() => f.client.close());
  const seqs = [];
  f.client.on('message.delta', event => seqs.push(event.seq));
  const socket = await f.connect();
  for (const seq of [4, 4, 2]) notify(socket, 'message.delta', { session_id: 's1', seq });
  assert.deepEqual(seqs, [4, 4, 2]);
  assert.deepEqual(f.client.getSeqWatermarks(), { s1: 4 });
});

test('truncated replay skips incomplete history but dispatches live frames beyond the server head', async t => {
  const f = makeGateway(); t.after(() => f.client.close());
  const seqs = [];
  f.client.on('message.delta', event => seqs.push(event.seq));
  const first = await f.connect(); ready(first, 'epoch-a');
  notify(first, 'message.delta', { session_id: 's1', seq: 1 });
  f.client.invalidate();
  const second = await f.connect();
  const barrier = f.client.sessionReplayBarrier('s1');
  notify(second, 'message.delta', { session_id: 's1', seq: 8 });
  notify(second, 'message.delta', { session_id: 's1', seq: 11 });
  respondReplay(second, { epoch: 'epoch-a', truncated: true, latest_seq: 10,
    events: [{ type: 'message.delta', session_id: 's1', seq: 9 }] });
  assert.equal(await barrier, true);
  assert.deepEqual(seqs, [1, 11]);
  assert.deepEqual(f.client.getSeqWatermarks(), { s1: 11 });
});

test('closing during replay invalidates its barrier and ignores stale socket frames', async t => {
  const f = makeGateway(); t.after(() => f.client.close());
  const seqs = [];
  f.client.on('message.delta', event => seqs.push(event.seq));
  const first = await f.connect();
  notify(first, 'message.delta', { session_id: 's1', seq: 1 });
  f.client.invalidate();
  const second = await f.connect();
  const barrier = f.client.sessionReplayBarrier('s1');
  const pending = assert.rejects(f.client.request('session.list'), /fixture closed/);
  f.client.invalidate('fixture closed');
  await pending;
  assert.equal(await barrier, false);
  notify(second, 'message.delta', { session_id: 's1', seq: 2 });
  assert.deepEqual(seqs, [1]);
  assert.equal(f.client.connectionState, 'closed');
});

test('event and state subscriptions expose explicit unsubscribe functions', async t => {
  const f = makeGateway(); t.after(() => f.client.close());
  const states = []; const events = [];
  const offState = f.client.onState(state => states.push(state));
  const offEvent = f.client.onAny(event => events.push(event));
  const socket = await f.connect();
  offState(); offEvent();
  notify(socket, 'message.delta', { session_id: 's1', seq: 1 });
  f.client.close();
  assert.deepEqual(states, ['idle', 'connecting', 'open']);
  assert.deepEqual(events, []);
});

test('real loopback WebSocket carries request/result/error, notification and delayed server answer', { timeout: 5000 }, async t => {
  const fixture = await loopbackFixture();
  const client = new gateway.JsonRpcGatewayClient({ requestTimeoutMs: 1000, connectTimeoutMs: 1000, heartbeatIntervalMs: 0 });
  t.after(async () => { client.close(); await fixture.close(); });
  await client.connect(fixture.url);
  const socket = await fixture.socket();
  const received = [];
  socket.on('message', bytes => {
    const frame = JSON.parse(bytes.toString()); received.push(frame);
    if (frame.method === 'session.list') socket.send(JSON.stringify({ jsonrpc: '2.0', id: frame.id, result: { sessions: [] } }));
    if (frame.method === 'fixture.error') socket.send(JSON.stringify({ jsonrpc: '2.0', id: frame.id, error: { code: -32601, message: 'fixture missing method' } }));
  });
  assert.deepEqual(await client.request('session.list'), { sessions: [] });
  await assert.rejects(client.request('fixture.error'), error => error.code === -32601);
  const eventPromise = new Promise(resolve => client.on('message.delta', resolve));
  socket.send(JSON.stringify({ jsonrpc: '2.0', method: 'event', params: { type: 'message.delta', session_id: 's1', seq: 1 } }));
  assert.equal((await eventPromise).seq, 1);
  const requestPromise = new Promise(resolve => client.onRequest(resolve));
  socket.send(JSON.stringify({ jsonrpc: '2.0', id: 'real-ask', method: 'clarify', params: { session_id: 's1' } }));
  const delayed = await requestPromise;
  const replyPromise = once(socket, 'message');
  delayed.respond({ answer: 'fixture response' });
  assert.deepEqual(JSON.parse((await replyPromise)[0].toString()), {
    jsonrpc: '2.0', id: 'real-ask', result: { answer: 'fixture response' },
  });
  assert.equal(received.length, 3);
});
