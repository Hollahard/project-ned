use hermes_broker_adapter::KvCacheMode;

#[test]
fn test_kv_cache_mode_parsing_and_payload_strings() {
    assert_eq!(KvCacheMode::parse("FP16").unwrap(), KvCacheMode::Fp16);
    assert_eq!(KvCacheMode::Fp16.to_payload_string(), "FP16");

    assert_eq!(KvCacheMode::parse("Q4").unwrap(), KvCacheMode::Q4);
    assert_eq!(KvCacheMode::parse("4,4").unwrap(), KvCacheMode::Q4);
    assert_eq!(KvCacheMode::Q4.to_payload_string(), "4,4");

    assert_eq!(KvCacheMode::parse("Q6").unwrap(), KvCacheMode::Q6);
    assert_eq!(KvCacheMode::parse("6,6").unwrap(), KvCacheMode::Q6);
    assert_eq!(KvCacheMode::Q6.to_payload_string(), "6,6");

    assert_eq!(KvCacheMode::parse("Q8").unwrap(), KvCacheMode::Q8);
    assert_eq!(KvCacheMode::parse("8,8").unwrap(), KvCacheMode::Q8);
    assert_eq!(KvCacheMode::Q8.to_payload_string(), "8,8");

    // Custom K,V
    assert_eq!(KvCacheMode::parse("4,8").unwrap(), KvCacheMode::Custom(4, 8));
    assert_eq!(KvCacheMode::Custom(4, 8).to_payload_string(), "4,8");
}

#[test]
fn test_kv_cache_mode_rejects_invalid() {
    assert!(KvCacheMode::parse("Q1").is_err());
    assert!(KvCacheMode::parse("9,9").is_err());
    assert!(KvCacheMode::parse("garbage").is_err());
}
