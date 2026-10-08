const checks = [];
function assert(value, label) { if (!value) throw new Error(label); checks.push(label); }
const transport = window.__HERMES_NATIVE_TRANSPORT__;
assert(transport && Object.isFrozen(transport), 'native-injection-before-entry');
const methods = ['api','getConnection','getConnectionFor','getGatewayWsUrl','getGatewayWsUrlFor','revalidateConnection','touchBackend','getVersion','getBootProgress','getRecentLogs','getBootstrapState','resetBootstrap','revealLogs'];
for (const method of methods) {
  try { await transport.invoke('hermes_host_request', {method,args:[]}); throw new Error('Unexpected success'); }
  catch (error) { assert(error.code === 'HERMES_HOST_CAPABILITY_UNAVAILABLE' && error.capability === method, `honest-unavailable:${method}`); }
}
try { await transport.invoke('hermes_host_request',{method:'runCommand',args:[]}); throw new Error('Unexpected success'); }
catch (error) { assert(error.code === 'HERMES_HOST_INVALID_REQUEST', 'native-unknown-method-rejected'); }
try { await window.__TAURI__.core.invoke('plugin:window|create', {options:{label:'untrusted',url:'https://example.com'}}); throw new Error('Unexpected success'); }
catch (error) { assert(String(error).includes('not allowed'), 'window-create-acl-denied'); }
try { await window.__TAURI__.event.emit('hermes:host:event', {name:'backend-exit',payload:{}}); throw new Error('Unexpected success'); }
catch (error) { assert(String(error).includes('not allowed'), 'event-emit-acl-denied'); }
let events = 0;
const off = await transport.subscribe('hermes:host:event', event => {
  if (event.name === 'boot-progress' && event.payload.stage === 'binding-fixture') events++;
});
await window.__TAURI__.core.invoke('hermes_binding_fixture', {phase:'event'});
await new Promise(resolve => setTimeout(resolve, 100));
assert(events === 1, 'native-event-payload-delivered');
off();
await window.__TAURI__.core.invoke('hermes_binding_fixture', {phase:'event'});
await new Promise(resolve => setTimeout(resolve, 100));
assert(events === 1, 'native-event-unsubscribe');
await window.__TAURI__.core.invoke('hermes_binding_fixture', {phase:'finish',checks});
