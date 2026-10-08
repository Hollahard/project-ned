(() => {
  if (window !== window.top) return;
  let errors = 0;
  let rejections = 0;
  window.addEventListener('error', () => { errors++; });
  window.addEventListener('unhandledrejection', () => { rejections++; });
  window.addEventListener('DOMContentLoaded', () => {
    const started = performance.now();
    let stableSince;
    const timer = setInterval(async () => {
      const notice = document.getElementById('hermes-native-feasibility-notice');
      const mounted = (document.getElementById('root')?.childElementCount ?? 0) > 0;
      const shell = !!document.querySelector('[data-contrib-shell]');
      const dialog = [...document.querySelectorAll('[role=dialog][aria-modal=true]')].find(node =>
        node.querySelector('h2')?.textContent === "Hermes couldn't start");
      const crash = [...document.querySelectorAll('h2')].some(node =>
        node.textContent === 'Something broke in the interface');
      const message = dialog?.textContent.includes('Hermes native host operation getConnection is unavailable. Managed backend integration is pending.');
      const expected = notice?.dataset.bootstrap === 'resolved' && mounted && shell && dialog && message && !crash && !errors && !rejections;
      if (expected) stableSince ??= performance.now();
      else stableSince = undefined;
      if (!(stableSince && performance.now() - stableSince >= 2000) && performance.now() - started < 20000) return;
      clearInterval(timer);
      const checks = [];
      if (notice) checks.push('retained-wrapper-evaluated');
      if (window.hermesDesktop && window.__HERMES_NATIVE_TRANSPORT__) checks.push('host-adapter-installed');
      if (notice?.dataset.bootstrap === 'resolved') checks.push('retained-bootstrap-resolved');
      if (mounted) checks.push('retained-root-mounted');
      if (shell) checks.push('retained-contrib-shell-mounted');
      if (dialog) checks.push('retained-boot-failure-dialog');
      if (message) checks.push('readable-backend-unavailable-message');
      if (!crash) checks.push('react-crash-absent');
      if (!errors) checks.push('uncaught-errors-absent');
      if (!rejections) checks.push('unhandled-rejections-absent');
      if (stableSince && performance.now() - stableSince >= 2000) checks.push('retained-state-stable');
      if (notice?.dataset.bootstrap === 'stopped') checks.push('retained-bootstrap-stopped');
      // Booleans encoded as reviewed labels only: no raw DOM/error/user data.
      await window.__TAURI__.core.invoke('hermes_binding_fixture', {phase:'finish',checks});
    }, 100);
  }, {once:true});
})();
