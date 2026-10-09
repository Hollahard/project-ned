use hermes_memory_bridge::{MemoryBridge, MemoryItemRecord};

#[test]
fn test_stale_result_fencing_excludes_deleted_and_rewound() {
    let mut bridge = MemoryBridge::new();
    let query_vec = vec![1.0, 0.0, 0.0, 0.0];

    // Item 1: Perfect match, active
    bridge.insert(MemoryItemRecord {
        item_id: "match-active".to_string(),
        session_id: "sess-d".to_string(),
        text: "Active relevant knowledge".to_string(),
        vector: vec![1.0, 0.0, 0.0, 0.0],
        tombstone: false,
        revision: 1,
        timestamp: 100.0,
    });

    // Item 2: Perfect match, but DELETED (tombstone)
    bridge.insert(MemoryItemRecord {
        item_id: "match-deleted".to_string(),
        session_id: "sess-d".to_string(),
        text: "Deleted secret info that should not leak".to_string(),
        vector: vec![1.0, 0.0, 0.0, 0.0],
        tombstone: true,
        revision: 2,
        timestamp: 105.0,
    });

    // Item 3: Partial match, active
    bridge.insert(MemoryItemRecord {
        item_id: "partial-active".to_string(),
        session_id: "sess-d".to_string(),
        text: "Partial match knowledge".to_string(),
        vector: vec![0.8, 0.2, 0.0, 0.0],
        tombstone: false,
        revision: 1,
        timestamp: 110.0,
    });

    // Search KNN
    let results = bridge.search_knn(&query_vec, 10, 0.5);

    // Assert: Only active items are returned. The deleted item MUST NOT be present!
    assert_eq!(results.len(), 2);
    assert_eq!(results[0].0.item_id, "match-active");
    assert_eq!(results[1].0.item_id, "partial-active");

    for (item, _) in &results {
        assert_ne!(item.item_id, "match-deleted", "Tombstoned item leaked past stale fence!");
        assert!(!item.tombstone);
    }
}
