use hermes_broker_adapter::{
    ArtifactFingerprint, BenchmarkTelemetry, ProfilerMeasurementCache,
};

#[test]
fn test_artifact_fingerprint_matching_and_cache_retrieval() {
    let mut cache = ProfilerMeasurementCache::new();

    let fp1 = ArtifactFingerprint::new("hash_weights_v1", "hash_tok_v1", "hash_template_v1");
    let telemetry = BenchmarkTelemetry::new(18.2, 72.0, 8 * 1024 * 1024 * 1024, 32 * 1024 * 1024 * 1024);

    cache.store("model-qwen", fp1.clone(), telemetry.clone());
    assert_eq!(cache.len(), 1);

    // Same fingerprint retrieves telemetry
    let retrieved = cache.get("model-qwen", &fp1);
    assert!(retrieved.is_some());
    assert_eq!(retrieved.unwrap().ttft_ms, 18.2);
}

#[test]
fn test_cache_invalidated_when_weights_digest_changes() {
    let mut cache = ProfilerMeasurementCache::new();

    let fp_original = ArtifactFingerprint::new("weights_v1", "tok_v1", "jinja_v1");
    let telemetry = BenchmarkTelemetry::new(20.0, 65.0, 10 * 1024 * 1024 * 1024, 32 * 1024 * 1024 * 1024);

    cache.store("model-mistral", fp_original.clone(), telemetry);

    // Weights file was altered or retouched: weights digest changed
    let fp_modified = ArtifactFingerprint::new("weights_v2_modified", "tok_v1", "jinja_v1");
    assert!(!fp_original.matches(&fp_modified));

    // Get returns None because fingerprint changed
    assert!(cache.get("model-mistral", &fp_modified).is_none());

    // Explicit invalidate_if_changed evicts stale measurement
    let invalidated = cache.invalidate_if_changed("model-mistral", &fp_modified);
    assert!(invalidated);
    assert!(!cache.is_cached("model-mistral"));
    assert_eq!(cache.len(), 0);
}

#[test]
fn test_cache_invalidated_when_template_or_tokenizer_changes() {
    let mut cache = ProfilerMeasurementCache::new();

    let fp_original = ArtifactFingerprint::new("weights_v1", "tok_v1", "jinja_v1");
    let telemetry = BenchmarkTelemetry::new(20.0, 65.0, 10 * 1024 * 1024 * 1024, 32 * 1024 * 1024 * 1024);
    cache.store("model-llama", fp_original, telemetry);

    // Jinja template edited
    let fp_new_template = ArtifactFingerprint::new("weights_v1", "tok_v1", "jinja_v2_edited");
    assert!(cache.get("model-llama", &fp_new_template).is_none());
    assert!(cache.invalidate_if_changed("model-llama", &fp_new_template));

    // Tokenizer updated
    let fp_new_tok = ArtifactFingerprint::new("weights_v1", "tok_v2_updated", "jinja_v1");
    cache.store("model-llama", fp_new_tok.clone(), BenchmarkTelemetry::new(21.0, 64.0, 10 * 1024 * 1024 * 1024, 32 * 1024 * 1024 * 1024));
    assert!(cache.is_cached("model-llama"));

    cache.invalidate("model-llama");
    assert!(!cache.is_cached("model-llama"));
}
