(() => {
  const local = (location.protocol === 'http:' && location.host === 'tauri.localhost') ||
    (location.protocol === 'tauri:' && location.host === 'localhost');
  if (!local || window !== window.top || window.__HERMES_NATIVE_TRANSPORT__) return;
  Object.defineProperty(window, '__HERMES_NATIVE_TRANSPORT__', {
    configurable: false, writable: false,
    value: Object.freeze({
      invoke(command, payload) {
        if (command !== 'hermes_host_request') return Promise.reject(new Error('Unknown host command'));
        return window.__TAURI__.core.invoke(command, payload);
      },
      subscribe(channel, listener) {
        if (channel !== 'hermes:host:event') return Promise.reject(new Error('Unknown host channel'));
        return window.__TAURI__.event.listen(channel, event => listener(event.payload));
      }
    })
  });
})();
