const checks = [];
function assert(value, label) { if (!value) throw new Error(label); checks.push(label); }
const transport = window.__HERMES_NATIVE_TRANSPORT__;
async function rejected(operation, payload, code, label) {
  try { await transport.control(operation, payload); }
  catch (error) { assert(error?.code === code, label); return; }
  throw new Error(label);
}
const profileId = 'native-control-proof';
const profile = {
  artifact_id: 'native-fixture-artifact', revision: 'native-fixture-bytes',
  model_name: 'native-fixture-model', expected_model_path: 'C:/models/native-fixture-model',
  context_length: 2048, cache_size: 2048, cache_mode: 'q4', chunk_size: 256,
};
try {
  assert(transport && Object.isFrozen(transport) && typeof transport.control === 'function', 'control-native-transport-installed');
  const phase = document.documentElement.dataset.controlPhase;
  if (phase === 'unavailable') {
    await rejected('runtime.status', {}, 'CONTROL_UNAVAILABLE', 'control-unconfigured-status-unavailable');
    await rejected('profiles.schema', {}, 'CONTROL_UNAVAILABLE', 'control-unconfigured-schema-unavailable');
    await rejected('profiles.list', {}, 'CONTROL_UNAVAILABLE', 'control-unconfigured-list-unavailable');
  } else {
    const status = await transport.control('runtime.status', {});
    assert(status.state === 'detached' && status.runtime_attached === false && status.admission_allowed === false && status.active_profile === null && status.engine_observed === false, 'control-owned-worker-truthfully-detached');
    await rejected('service.describe', {}, 'CONTROL_UNAVAILABLE', 'control-owner-describe-not-renderer-operation');
    await rejected('service.shutdown', {}, 'CONTROL_UNAVAILABLE', 'control-owner-shutdown-not-renderer-operation');
    await rejected('model.load', {}, 'CONTROL_UNAVAILABLE', 'control-model-loading-unavailable');
    if (phase === 'create') {
      const schema = await transport.control('profiles.schema', {});
      assert(schema.schema_source === 'hermes_inference.LoadProfile' && schema.validation_scope === 'schema' && schema.artifact_verification === false && schema.fields.length === 10, 'control-real-worker-schema');
      const validated = await transport.control('profiles.validate', {profile});
      assert(validated.profile.cache_mode === '4,4' && validated.profile.max_batch_size === 1 && validated.validation_scope === 'schema' && validated.artifact_verified === false, 'control-real-worker-profile-normalization');
      await rejected('profiles.validate', {profile:{...profile,cache_size:257}}, 'INVALID_PROFILE', 'control-invalid-profile-leaves-worker-usable');
      const saved = await transport.control('profiles.save', {profile_id:profileId,name:'Native control fixture',expected_revision:null,profile});
      assert(saved.profile_id === profileId && Number.isSafeInteger(saved.revision) && saved.revision > 0 && saved.validation_scope === 'schema', 'control-profile-created-through-native-command');
      const listed = await transport.control('profiles.list', {});
      assert(listed.profiles.length === 1 && listed.profiles[0].profile_id === profileId && listed.profiles[0].revision === saved.revision, 'control-created-profile-listed');
      await rejected('profiles.save', {profile_id:profileId,name:'Conflict must not overwrite',expected_revision:null,profile}, 'REVISION_CONFLICT', 'control-optimistic-conflict-does-not-overwrite');
      const fetched = await transport.control('profiles.get', {profile_id:profileId});
      assert(fetched.name === 'Native control fixture' && fetched.revision === saved.revision && fetched.profile.cache_mode === '4,4', 'control-saved-profile-remains-normalized');
    } else if (phase === 'reopen') {
      const fetched = await transport.control('profiles.get', {profile_id:profileId});
      assert(fetched.name === 'Native control fixture' && fetched.profile.cache_mode === '4,4' && fetched.profile.artifact_id === profile.artifact_id, 'control-profile-persists-across-native-shell-launch');
      await rejected('profiles.delete', {profile_id:profileId,expected_revision:fetched.revision+1}, 'REVISION_CONFLICT', 'control-reopened-profile-rejects-stale-delete');
      const changed = await transport.control('profiles.save', {profile_id:profileId,name:'Updated native fixture',expected_revision:fetched.revision,profile:{...profile,cache_mode:'q6'}});
      assert(changed.revision > fetched.revision, 'control-profile-update-advances-revision');
      const updated = await transport.control('profiles.get', {profile_id:profileId});
      assert(updated.name === 'Updated native fixture' && updated.profile.cache_mode === '6,6', 'control-updated-profile-is-normalized');
      const deleted = await transport.control('profiles.delete', {profile_id:profileId,expected_revision:changed.revision});
      assert(deleted.deleted === true && deleted.profile_id === profileId, 'control-profile-deleted-through-native-command');
      const listed = await transport.control('profiles.list', {});
      assert(listed.profiles.length === 0, 'control-profile-list-empty-after-delete');
      await rejected('profiles.get', {profile_id:profileId}, 'PROFILE_NOT_FOUND', 'control-deleted-profile-is-unavailable');
    } else { throw new Error('Unknown control fixture phase'); }
    const after = await transport.control('runtime.status', {});
    assert(after.runtime_attached === false && after.admission_allowed === false, 'control-worker-healthy-after-profile-operations');
  }
} catch {
  checks.push('control-native-fixture-failed');
}
await window.__TAURI__.core.invoke('hermes_binding_fixture', {phase:'finish',checks});
