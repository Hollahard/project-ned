// Binding-fixture initialization script. Load only with unchanged retained
// index.html and an explicitly fresh fixture-owned control-worker state.
// It neither installs a bridge nor changes application/source/plugin state.
(() => {
  if (window !== window.top) return;
  const checks = new Set();
  const failures = Object.freeze({
    bootstrap: 'profiles-failed-bootstrap',
    dismiss: 'profiles-failed-boot-dismissal',
    native: 'profiles-failed-native-preflight',
    route: 'profiles-failed-settings-route',
    connect: 'profiles-failed-settings-connection',
    fill: 'profiles-failed-form-input',
    validate: 'profiles-failed-validation',
    create: 'profiles-failed-create',
    catalog: 'profiles-failed-catalog',
    list: 'profiles-failed-list',
    read: 'profiles-failed-read',
    update: 'profiles-failed-update',
    delete: 'profiles-failed-delete',
    stable: 'profiles-failed-final-stability'
  });
  let stage = 'bootstrap';
  let errors = 0;
  let rejections = 0;
  let finished = false;
  window.addEventListener('error', () => { errors++; });
  window.addEventListener('unhandledrejection', () => { rejections++; });

  const run = async () => {
    const deadline = performance.now() + 55_000;
    const fixtureId = 'native-fixture-profile';
    const fixtureName = 'Native fixture profile';
    const fixtureModel = 'native-fixture-exl3';
    // LoadProfile canonicalizes Windows drive/path casing lexically.
    const fixtureFolder = 'c:\\hermes-native-fixture\\schema-only-exl3';
    const fail = () => { throw new Error('Profile fixture condition failed'); };
    const assert = value => { if (!value) fail(); };
    const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
    const crash = () => [...document.querySelectorAll('h2')].some(node => node.textContent === 'Something broke in the interface');
    const healthy = () => { assert(!crash() && errors === 0 && rejections === 0); };
    const bootDialog = () => [...document.querySelectorAll('[role="dialog"][aria-modal="true"]')].find(node =>
      node.querySelector('h2')?.textContent === "Hermes couldn't start");
    const panel = () => document.querySelector('[data-native-model-profiles]');
    const status = () => panel()?.querySelector('[data-native-profile-status]');
    const button = text => [...(panel()?.querySelectorAll('button') ?? [])].find(node => node.textContent.trim() === text);
    const input = name => panel()?.querySelector(`[name="${name}"]`);
    const wait = async (predicate, limit = 6000) => {
      const end = Math.min(deadline, performance.now() + limit);
      while (performance.now() < end) {
        healthy();
        const value = predicate();
        if (value) return value;
        await pause(75);
      }
      fail();
    };
    const bounded = async promise => {
      const remaining = Math.min(6000, Math.max(0, deadline - performance.now()));
      let timer;
      try {
        return await Promise.race([promise, new Promise((_, reject) => {
          timer = setTimeout(() => reject(new Error('Profile fixture deadline')), remaining);
        })]);
      } finally { clearTimeout(timer); }
    };
    const native = (operation, payload) => bounded(window.__HERMES_NATIVE_TRANSPORT__.control(operation, payload));
    const click = async text => {
      const target = await wait(() => {
        const candidate = button(text);
        return candidate && !candidate.matches(':disabled') && candidate;
      });
      target.click();
      await pause(75);
      healthy();
    };
    const setValue = async (name, value) => {
      const target = input(name);
      assert(target && !target.matches(':disabled'));
      const prototype = target instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
      assert(setter);
      // Native prototype setter bypasses React's instance value tracker. The
      // real delegated onChange then updates application state through input.
      setter.call(target, value);
      target.dispatchEvent(new Event('input', { bubbles: true }));
      target.dispatchEvent(new Event('change', { bubbles: true }));
      await pause(75);
      assert(input(name)?.value === value);
    };
    const expectStatus = text => wait(() => status()?.textContent === text && status()?.dataset.failed === 'false');
    const expectProfile = (saved, context, cache, chunk) => {
      assert(saved?.profile_id === fixtureId && saved?.name === fixtureName && saved?.validation_scope === 'schema');
      const profile = saved.profile;
      assert(profile?.model_name === fixtureModel && profile?.expected_model_path === fixtureFolder);
      assert(profile?.context_length === context && profile?.cache_size === cache && profile?.chunk_size === chunk);
      assert(profile?.cache_mode === '4,4' && profile?.max_batch_size === 1 && profile?.vision === false);
    };

    try {
      await wait(() => document.getElementById('hermes-native-feasibility-notice')?.dataset.bootstrap === 'resolved', 20_000);
      assert(document.getElementById('hermes-native-feasibility-notice')?.dataset.modelProfiles === 'registered');
      assert(document.querySelector('[data-contrib-shell]'));
      checks.add('profiles-retained-bootstrap-resolved');
      checks.add('profiles-retained-contribution-registered');

      stage = 'dismiss';
      const dialog = await wait(bootDialog);
      assert(dialog.textContent.includes('Hermes native host operation getConnection is unavailable. Managed backend integration is pending.'));
      checks.add('profiles-truthful-backend-unavailable');
      const close = dialog.querySelector('[data-slot="dialog-close-button"]') ?? dialog.querySelector('button[aria-label="Close"]');
      assert(close instanceof HTMLButtonElement && !close.disabled);
      close.click();
      await wait(() => !bootDialog());
      checks.add('profiles-real-boot-dialog-dismissed');

      stage = 'native';
      assert(typeof window.__HERMES_NATIVE_TRANSPORT__?.control === 'function');
      const runtime = await native('runtime.status', {});
      assert(runtime?.state === 'detached' && runtime.runtime_attached === false && runtime.admission_allowed === false && runtime.active_profile === null && runtime.engine_observed === false);
      const initial = await native('profiles.list', {});
      // Never delete/modify anything in a pre-existing store. The outer owner
      // must also create and attest a fresh directory before starting this mode.
      assert(Array.isArray(initial?.profiles) && initial.profiles.length === 0);
      checks.add('profiles-native-runtime-detached');
      checks.add('profiles-fresh-store-confirmed');

      stage = 'route';
      window.location.hash = '/settings?tab=plugins&plugin=native-model-profiles%3Aprofiles';
      await wait(panel, 10_000);
      const route = new URL(window.location.hash.slice(1), window.location.origin);
      assert(route.pathname === '/settings' && route.searchParams.get('tab') === 'plugins' && route.searchParams.get('plugin') === 'native-model-profiles:profiles');
      assert(panel().querySelector('h2')?.textContent === 'Local model profiles');
      checks.add('profiles-retained-settings-route-mounted');

      stage = 'connect';
      await wait(() => status()?.textContent === 'Profiles are stored locally. No inference runtime is connected.' ||
        (status()?.dataset.failed === 'true' && button('Retry connection')));
      if (status()?.dataset.failed === 'true') {
        await click('Retry connection');
        checks.add('profiles-connection-retry-used');
      }
      await expectStatus('Profiles are stored locally. No inference runtime is connected.');
      assert(!button('Save profile').matches(':disabled'));
      checks.add('profiles-control-service-connected');

      stage = 'fill';
      await setValue('profile-name', fixtureName);
      await setValue('profile-id', fixtureId);
      await setValue('model-name', fixtureModel);
      await setValue('model-folder', fixtureFolder);
      await setValue('cache-mode', '4,4');
      assert(panel().querySelector('form').checkValidity());
      checks.add('profiles-react-form-input-applied');

      stage = 'validate';
      await click('Validate settings');
      await expectStatus('Settings are valid. Model compatibility and VRAM use remain unchecked.');
      checks.add('profiles-form-validation-confirmed');

      stage = 'create';
      await click('Save profile');
      await expectStatus('Profile saved locally. No model was loaded.');
      const created = await native('profiles.get', { profile_id: fixtureId });
      expectProfile(created, 2048, 2048, 256);
      assert(created.revision === 1 && input('profile-id').disabled);
      checks.add('profiles-form-create-confirmed');

      if (window.__HERMES_CATALOG_FIXTURE__ === true) {
        stage = 'catalog';
        const fixture = phase => bounded(window.__TAURI__.core.invoke('hermes_binding_fixture', { phase }));
        const paths = await fixture('catalog-inputs');
        const result = () => panel()?.querySelector('[data-native-model-inspection]');
        const settled = () => Number(panel()?.dataset.nativeInspectionSettled ?? 0);
        const waitHeld = async () => {
          const end = performance.now() + 4000;
          while (performance.now() < end) {
            if ((await fixture('catalog-held')).held) return;
            await pause(25);
          }
          fail();
        };
        await setValue('model-folder', paths.partial);
        await click('Inspect metadata');
        await wait(() => result()?.querySelector('h3')?.textContent === 'Model files are incomplete');
        assert(result().textContent.includes('model-00002-of-00002.safetensors'));
        assert(result().textContent.includes('Runtime compatibility and VRAM use remain unchecked. No model was loaded.'));
        checks.add('catalog-profiles-real-partial-metadata-displayed');
        checks.add('catalog-profiles-all-missing-shards-displayed');
        checks.add('catalog-profiles-no-runtime-certification');
        await setValue('model-folder', paths.complete);
        assert(!result());
        checks.add('catalog-profiles-edit-clears-old-result');
        await fixture('catalog-hold-next');
        let settledBefore = settled();
        await click('Inspect metadata'); await waitHeld();
        await setValue('model-folder', paths.invalid);
        await fixture('catalog-release'); await wait(() => settled() > settledBefore);
        assert(!result());
        checks.add('catalog-profiles-late-real-result-ignored-after-edit');
        await setValue('model-folder', paths.partial);
        await fixture('catalog-hold-next');
        settledBefore = settled();
        await click('Inspect metadata'); await waitHeld();
        await click(fixtureName);
        await expectStatus('Profile loaded. Model files have not been verified.');
        await fixture('catalog-release'); await wait(() => settled() > settledBefore);
        assert(!result() && input('model-folder')?.value === fixtureFolder);
        checks.add('catalog-profiles-late-real-result-ignored-after-selection');
        const unchanged = await native('profiles.get', { profile_id: fixtureId });
        expectProfile(unchanged, 2048, 2048, 256);
        assert(unchanged.revision === created.revision);
        checks.add('catalog-profiles-inspection-does-not-mutate-saved-settings');
      }

      stage = 'list';
      await click('Refresh');
      await expectStatus('Profile list refreshed.');
      assert(button(fixtureName));
      const listed = await native('profiles.list', {});
      assert(listed?.profiles?.length === 1 && listed.profiles[0].profile_id === fixtureId && listed.profiles[0].revision === created.revision);
      checks.add('profiles-form-list-confirmed');

      stage = 'read';
      await click('New profile');
      assert(input('profile-id')?.value === '' && input('model-folder')?.value === '');
      await click(fixtureName);
      await expectStatus('Profile loaded. Model files have not been verified.');
      assert(input('profile-id')?.value === fixtureId && input('model-folder')?.value === fixtureFolder && input('cache-mode')?.value === '4,4');
      checks.add('profiles-form-read-confirmed');

      stage = 'update';
      await setValue('context-length', '4096');
      await setValue('cache-size', '4096');
      await setValue('chunk-size', '512');
      await click('Save profile');
      await expectStatus('Profile saved locally. No model was loaded.');
      const updated = await native('profiles.get', { profile_id: fixtureId });
      expectProfile(updated, 4096, 4096, 512);
      assert(updated.revision === created.revision + 1);
      checks.add('profiles-form-update-confirmed');

      stage = 'delete';
      await click('Delete profile');
      assert(button('Confirm deletion'));
      const beforeDelete = await native('profiles.get', { profile_id: fixtureId });
      assert(beforeDelete.revision === updated.revision);
      checks.add('profiles-delete-requires-confirmation');
      await click('Confirm deletion');
      await expectStatus('Profile deleted.');
      assert(input('profile-id')?.value === '' && !button('Delete profile') && !button(fixtureName));
      const finalList = await native('profiles.list', {});
      assert(Array.isArray(finalList?.profiles) && finalList.profiles.length === 0);
      let missing = false;
      try { await native('profiles.get', { profile_id: fixtureId }); }
      catch (error) { missing = error?.code === 'PROFILE_NOT_FOUND'; }
      assert(missing);
      checks.add('profiles-form-delete-confirmed');
      checks.add('profiles-fixture-record-cleaned');

      stage = 'stable';
      await pause(2000);
      healthy();
      assert(panel() && !bootDialog() && performance.now() < deadline);
      checks.add('profiles-retained-state-stable');
      checks.add('profiles-crud-complete');
    } catch {
      checks.add('profiles-observer-failed');
      checks.add(failures[stage]);
    } finally {
      if (!crash()) checks.add('profiles-react-crash-absent');
      if (!errors) checks.add('profiles-uncaught-errors-absent');
      if (!rejections) checks.add('profiles-unhandled-rejections-absent');
      if (!finished) {
        finished = true;
        // Finite reviewed labels only. Never export DOM text, exception text,
        // saved DTOs, paths, credentials or arbitrary renderer data.
        try {
          await window.__TAURI__.core.invoke('hermes_binding_fixture', { phase: 'finish', checks: [...checks] });
        } catch { /* Outer owner deadline captures missing native completion. */ }
      }
    }
  };
  if (document.readyState === 'loading') window.addEventListener('DOMContentLoaded', () => { void run(); }, { once: true });
  else void run();
})();
