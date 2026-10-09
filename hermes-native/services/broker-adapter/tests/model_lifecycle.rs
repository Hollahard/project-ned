use hermes_broker_adapter::{
    BackendType, BrokerClient, BrokerState, KvCacheMode, LoadRequest,
};

#[test]
fn test_broker_model_load_and_unload_lifecycle() {
    let mut client = BrokerClient::new();
    assert_eq!(*client.state(), BrokerState::Unloaded);
    assert!(client.active_parameters().is_none());

    let req = LoadRequest::new("Qwen/Qwen2.5-Coder-32B-Instruct", BackendType::ExLlamaV3)
        .with_context(8192, 8192)
        .with_cache_mode(KvCacheMode::Q6)
        .with_batch_size(2);

    let effective = client.load_model(req).expect("Model load should succeed");
    assert_eq!(*client.state(), BrokerState::Ready);
    assert_eq!(effective.model_name, "Qwen/Qwen2.5-Coder-32B-Instruct");
    assert_eq!(effective.backend, BackendType::ExLlamaV3);
    assert_eq!(effective.max_seq_len, 8192);
    assert_eq!(effective.max_batch_size, 2);
    assert_eq!(effective.cache_mode, KvCacheMode::Q6);
    assert!(!effective.draft_enabled);

    assert_eq!(client.active_parameters(), Some(&effective));

    client.unload_model().expect("Unload should succeed");
    assert_eq!(*client.state(), BrokerState::Unloaded);
    assert!(client.active_parameters().is_none());
}

#[test]
fn test_broker_rejects_insufficient_cache_size() {
    let mut client = BrokerClient::new();
    let mut req = LoadRequest::new("test-model", BackendType::ExLlamaV3);
    req.max_seq_len = 8192;
    req.cache_size = 4096; // Less than max_seq_len

    let err = client.load_model(req).unwrap_err();
    assert!(err.contains("cache_size must cover max_seq_len"));
}
