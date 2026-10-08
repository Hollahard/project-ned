import { once } from 'node:events';
import { channel, gateway, WebSocketServer } from './upstream.mjs';

export function makeChannel(options = {}) {
  const sent = [];
  const transport = { send(text) { sent.push(JSON.parse(text)); } };
  const client = new channel.JsonRpcRequestChannel({ requestTimeoutMs: 1000, ...options });
  client.attach(transport);
  return {
    client, transport, sent,
    inbound(frame) { return client.handleFrame(JSON.stringify(frame)); },
    close() { client.detach(new Error('fixture disposed')); },
  };
}

export class FixtureSocket extends EventTarget {
  readyState = 0;
  sent = [];
  constructor(url) { super(); this.url = url; }
  send(text) {
    if (this.readyState !== WebSocket.OPEN) throw new Error('fixture socket is closed');
    this.sent.push(JSON.parse(text));
  }
  open() { this.readyState = WebSocket.OPEN; this.dispatchEvent(new Event('open')); }
  close() {
    this.readyState = WebSocket.CLOSED;
    const event = new Event('close');
    Object.defineProperties(event, { code: { value: 1000 }, reason: { value: 'fixture' } });
    this.dispatchEvent(event);
  }
  inbound(frame) { this.dispatchEvent(new MessageEvent('message', { data: JSON.stringify(frame) })); }
}

export function makeGateway(options = {}) {
  const sockets = [];
  const client = new gateway.JsonRpcGatewayClient({
    heartbeatIntervalMs: 0, heartbeatDeadlineMs: 0, connectTimeoutMs: 1000,
    requestTimeoutMs: 1000,
    socketFactory(url) { const socket = new FixtureSocket(url); sockets.push(socket); return socket; },
    ...options,
  });
  return {
    client, sockets,
    async connect() {
      const pending = client.connect('ws://fixture.invalid');
      const socket = sockets.at(-1);
      socket.open();
      await pending;
      return socket;
    },
  };
}

export function notify(socket, type, rest = {}) {
  socket.inbound({ jsonrpc: '2.0', method: 'event', params: { type, ...rest } });
}

export function ready(socket, epoch) {
  notify(socket, 'gateway.ready', { payload: { replay_epoch: epoch, heartbeat: false } });
  const capability = socket.sent.findLast(frame => frame.method === 'client.capabilities');
  socket.inbound({ jsonrpc: '2.0', id: capability.id, result: { declines_not_shown: true } });
}

export function respondReplay(socket, result) {
  const request = socket.sent.findLast(frame => frame.method === 'session.events.since');
  if (!request) throw new Error('Expected a reconnect replay request.');
  socket.inbound({ jsonrpc: '2.0', id: request.id, result });
  return request;
}

export async function loopbackFixture() {
  const server = new WebSocketServer({ host: '127.0.0.1', port: 0, perMessageDeflate: false });
  await once(server, 'listening');
  const connection = once(server, 'connection');
  return {
    server,
    url: `ws://127.0.0.1:${server.address().port}`,
    async socket() { return (await connection)[0]; },
    async close() {
      for (const socket of server.clients) socket.terminate();
      await new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
    },
  };
}
