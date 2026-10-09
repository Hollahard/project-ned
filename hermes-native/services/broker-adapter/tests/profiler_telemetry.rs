use hermes_broker_adapter::BenchmarkTelemetry;

#[test]
fn test_benchmark_telemetry_metrics_calculation() {
    let telemetry = BenchmarkTelemetry::new(
        14.5,                      // 14.5 ms TTFT
        85.2,                      // 85.2 tokens/sec
        12 * 1024 * 1024 * 1024,   // 12 GiB used
        32 * 1024 * 1024 * 1024,   // 32 GiB total (e.g. RTX 5090)
    );

    assert_eq!(telemetry.ttft_ms, 14.5);
    assert_eq!(telemetry.tokens_per_second, 85.2);
    assert_eq!(telemetry.vram_used_bytes, 12 * 1024 * 1024 * 1024);
    assert_eq!(telemetry.vram_total_bytes, 32 * 1024 * 1024 * 1024);
    assert_eq!(telemetry.vram_utilization_ratio(), 0.375);
}

#[test]
fn test_zero_vram_ratio_safe() {
    let telemetry = BenchmarkTelemetry::new(0.0, 0.0, 0, 0);
    assert_eq!(telemetry.vram_utilization_ratio(), 0.0);
}
