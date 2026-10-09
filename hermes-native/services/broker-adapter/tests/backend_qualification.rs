use hermes_broker_adapter::{BackendType, BrokerClient};

#[test]
fn test_qualification_order_exl3_primary() {
    // When both EXL3 and EXL2 are supported, EXL3 must be selected first
    let client = BrokerClient::with_supported_backends(vec![BackendType::ExLlamaV3, BackendType::ExLlamaV2]);
    let qualified = client.qualify_backend().expect("Qualification should succeed");
    assert_eq!(qualified, BackendType::ExLlamaV3);
    assert_eq!(qualified.priority(), 1);
}

#[test]
fn test_qualification_order_exl2_fallback_when_exl3_unavailable() {
    // When only EXL2 is supported (fallback scenario), EXL2 must be selected
    let client = BrokerClient::with_supported_backends(vec![BackendType::ExLlamaV2]);
    let qualified = client.qualify_backend().expect("Qualification should succeed with fallback");
    assert_eq!(qualified, BackendType::ExLlamaV2);
    assert_eq!(qualified.priority(), 2);
}

#[test]
fn test_qualification_fails_when_no_backend_available() {
    let client = BrokerClient::with_supported_backends(vec![]);
    let err = client.qualify_backend().unwrap_err();
    assert!(err.contains("No supported backend available"));
}
