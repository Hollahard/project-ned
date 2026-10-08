(() => {
  const local = (location.protocol === 'http:' && location.host === 'tauri.localhost') ||
    (location.protocol === 'tauri:' && location.host === 'localhost');
  if (!local || window !== window.top || window.__HERMES_NATIVE_TRANSPORT__) return;
  const previewNames = new Set(['preview-file-changed', 'preview-watch-failed']);
  const previewListeners = new Set();
  const documentId = crypto.randomUUID();
  Object.defineProperty(window, '__HERMES_NATIVE_EVENT_RECEIVER__', {
    configurable: false, writable: false,
    value: packet => {
      if (!packet || packet.documentId !== documentId) return;
      const envelope = packet.event;
      if (!envelope || !previewNames.has(envelope.name)) return;
      const payload = envelope.payload;
      if (!payload || typeof payload.id !== 'string' || payload.id.length > 128) return;
      if (envelope.name === 'preview-file-changed' &&
        (typeof payload.path !== 'string' || payload.path.length > 32767 ||
         typeof payload.url !== 'string' || payload.url.length > 131072)) return;
      if (envelope.name === 'preview-watch-failed' &&
        (typeof payload.error !== 'string' || payload.error.length > 64)) return;
      // This page-local receiver is a notification mechanism, not a trusted
      // action or a proof of authenticity inside the renderer itself.
      for (const listener of [...previewListeners]) {
        try { listener(envelope); }
        catch { console.error('HERMES_PREVIEW_LISTENER_FAILED'); }
      }
    }
  });
  Object.defineProperty(window, '__HERMES_NATIVE_TRANSPORT__', {
    configurable: false, writable: false,
    value: Object.freeze({
      invoke(command, payload) {
        if (command !== 'hermes_host_request') return Promise.reject(new Error('Unknown host command'));
        return window.__TAURI__.core.invoke(command, {...payload, documentId});
      },
      control(operation, payload) {
        return window.__TAURI__.core.invoke('hermes_control_request', {operation, payload});
      },
      inspectModel(modelPath) {
        return window.__TAURI__.core.invoke('hermes_model_inspect', {modelPath});
      },
      async subscribe(channel, listener) {
        if (channel !== 'hermes:host:event') return Promise.reject(new Error('Unknown host channel'));
        if (typeof listener !== 'function') throw new TypeError('Host event listener required');
        const localListener = envelope => listener(envelope);
        previewListeners.add(localListener);
        try {
          const off = await window.__TAURI__.event.listen(channel, event => {
            // Preview delivery is owner-bound. Never accept it from Tauri's
            // app-wide event bus, including an ANY-target subscription.
            if (!previewNames.has(event.payload?.name)) listener(event.payload);
          });
          let closed = false;
          return () => {
            if (closed) return;
            closed = true;
            previewListeners.delete(localListener);
            off();
          };
        } catch (error) {
          previewListeners.delete(localListener);
          throw error;
        }
      }
    })
  });
})();
