(async () => {
  const checks = [];
  const fixture = phase => window.__TAURI__.core.invoke('hermes_binding_fixture', { phase });
  const inspect = path => window.__HERMES_NATIVE_TRANSPORT__.inspectModel(path);
  const assert = value => { if (!value) throw Error('Catalog fixture condition'); };
  const rejects = async (path, codes) => { try { await inspect(path); return false; } catch (error) { return codes.includes(error?.code); } };
  try {
    assert(typeof window.__HERMES_NATIVE_TRANSPORT__?.inspectModel === 'function');
    checks.push('catalog-native-command-injected');
    if (document.body.dataset.catalogMode === 'unavailable') {
      assert(await rejects('C:/not-granted/model', ['CATALOG_UNAVAILABLE']));
      checks.push('catalog-unconfigured-host-unavailable');
    } else {
      const paths = await fixture('catalog-inputs');
      const full = await inspect(paths.complete);
      assert(full.status === 'metadata_inspected' && full.format === 'EXL3' && full.observed_tensor_count === 1 && full.missing_shards.length === 0);
      checks.push('catalog-real-complete-metadata');
      assert(full.runtime_compatible === null && full.load_certified === false && full.weights_content_hashed === false && full.weight_payload_bytes_read === 0);
      checks.push('catalog-no-load-or-content-hash-certification');
      const partial = await inspect(paths.partial);
      assert(partial.status === 'incomplete' && partial.observed_tensor_count === 1 && partial.index_tensor_count === 2 && partial.missing_shards.length === 1 && partial.missing_shards[0] === 'model-00002-of-00002.safetensors' && partial.fingerprint_partial === true);
      checks.push('catalog-real-partial-missing-shard');
      const invalid = await inspect(paths.invalid);
      assert(invalid.status === 'invalid' && invalid.load_certified === false);
      checks.push('catalog-real-malformed-metadata');
      assert(await rejects(paths.outside, ['CATALOG_OUTSIDE_GRANT', 'CATALOG_INVALID_REQUEST']));
      checks.push('catalog-renderer-cannot-grant-outside-path');
      assert(await rejects(paths.complete + '/../partial', ['CATALOG_OUTSIDE_GRANT', 'CATALOG_INVALID_REQUEST']));
      checks.push('catalog-parent-traversal-denied');
      assert((await inspect(paths.complete)).status === 'metadata_inspected');
      const retired = await fixture('catalog-retire');
      assert(retired.retired === true);
      assert(retired.cleanup?.verified === true && retired.cleanup.root_exit_code === 0 && retired.cleanup.stdout_eof && retired.cleanup.stderr_eof && retired.cleanup.job_empty);
      checks.push('catalog-real-child-exit-eof-and-empty-job');
      assert(await rejects(paths.complete, ['CATALOG_RETIRED', 'CATALOG_UNAVAILABLE']));
      checks.push('catalog-native-owner-retirement-permanent');
    }
  } catch { checks.push('catalog-fixture-failed'); }
  await window.__TAURI__.core.invoke('hermes_binding_fixture', { phase: 'finish', checks });
})();
