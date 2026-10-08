(() => {
  if (window !== window.top) return;
  window.addEventListener('DOMContentLoaded', () => {
    setTimeout(async () => {
      const notice = document.getElementById('hermes-native-feasibility-notice');
      const checks = [];
      if (notice) checks.push('retained-wrapper-evaluated');
      if (window.hermesDesktop && window.__HERMES_NATIVE_TRANSPORT__) checks.push('host-adapter-installed');
      if (document.getElementById('root')?.childElementCount === 0) checks.push('retained-root-empty');
      if (notice?.textContent.startsWith('Hermes native feasibility initialization stopped:')) {
        checks.push('retained-bootstrap-stopped');
        const method = notice.textContent.match(/(?:hermesDesktop|[A-Za-z_$][\w$]*)\.([A-Za-z_$][\w$]*) is not a function/);
        if (method) checks.push('missing-method:' + method[1]);
      }
      // No raw error, user content, config, browser storage or credential data.
      await window.__TAURI__.core.invoke('hermes_binding_fixture', {phase:'finish',checks});
    }, 3000);
  }, {once:true});
})();
