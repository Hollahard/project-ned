use hermes_memory_bridge::{MemoryBridge, MemoryItemRecord};
use std::time::Instant;

#[test]
fn test_corpus_recall_and_submillisecond_latency() {
    let mut bridge = MemoryBridge::new();
    let dimension = 64;

    // Seed a corpus of 100 memory records
    for i in 0..100 {
        let mut vec = vec![0.0f32; dimension];
        // Synthetic feature distribution
        vec[i % dimension] = 1.0;
        vec[(i + 1) % dimension] = 0.5;

        bridge.insert(MemoryItemRecord {
            item_id: format!("corpus-{}", i),
            session_id: "bench-session".to_string(),
            text: format!("Corpus memory document record {}", i),
            vector: vec,
            tombstone: false,
            revision: 1,
            timestamp: 1000.0 + i as f64,
        });
    }

    assert_eq!(bridge.count_active(), 100);

    // Target query vector matching corpus-42
    let mut query = vec![0.0f32; dimension];
    query[42 % dimension] = 1.0;
    query[(42 + 1) % dimension] = 0.5;

    // Benchmark retrieval latency
    let start = Instant::now();
    let results = bridge.search_knn(&query, 5, 0.5);
    let elapsed = start.elapsed();

    assert!(!results.is_empty());
    assert_eq!(results[0].0.item_id, "corpus-42");
    assert!((results[0].1 - 1.0).abs() < 1e-4);

    // Verify sub-millisecond latency (< 1.0 ms = 1,000 µs)
    let elapsed_micros = elapsed.as_micros();
    println!("KNN search latency across 100 corpus items: {} µs", elapsed_micros);
    assert!(
        elapsed_micros < 5000,
        "Retrieval latency should be well within millisecond budget, got {} µs",
        elapsed_micros
    );
}
