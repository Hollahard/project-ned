use hermes_gpu_coordinator::{GpuAuthorityCoordinator, GpuWorkerType, GATEWAY_BUSY_GAMING_MODE};

#[test]
fn test_admission_barrier_rejects_incoming_requests_during_gaming_mode() {
    let mut coordinator = GpuAuthorityCoordinator::default();

    // Inactive gaming mode: admissions succeed
    let lease1 = coordinator
        .request_admission(GpuWorkerType::PrimaryLlm, 16 * 1024 * 1024 * 1024)
        .expect("Primary LLM admission should succeed when gaming mode is inactive");
    assert!(lease1.active);

    // Engage Gaming Mode
    coordinator.activate_gaming_mode();
    assert!(coordinator.is_gaming_mode_active());

    // ADMISSION BARRIER: All incoming workers must be immediately rejected with GATEWAY_BUSY_GAMING_MODE
    let workers = [
        GpuWorkerType::PrimaryLlm,
        GpuWorkerType::DraftModel,
        GpuWorkerType::Vision,
        GpuWorkerType::Embeddings,
        GpuWorkerType::SpeechAudio,
        GpuWorkerType::Profiler,
    ];

    for worker in workers {
        let err = coordinator
            .request_admission(worker, 1024 * 1024 * 1024)
            .expect_err("Worker request must be rejected when gaming mode is active");
        assert!(
            err.contains(GATEWAY_BUSY_GAMING_MODE),
            "Error '{}' must contain '{}'",
            err,
            GATEWAY_BUSY_GAMING_MODE
        );
    }

    // Deactivate Gaming Mode: admissions resume cleanly
    coordinator.deactivate_gaming_mode();
    assert!(!coordinator.is_gaming_mode_active());

    let lease2 = coordinator
        .request_admission(GpuWorkerType::Embeddings, 1024 * 1024 * 1024)
        .expect("Embeddings admission should succeed after gaming mode deactivated");
    assert!(lease2.active);
}
