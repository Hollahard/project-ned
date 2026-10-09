use hermes_memory_bridge::{MemoryBridge, MemoryItemRecord};

#[test]
fn test_cold_crash_recovery_and_persistence() {
    let mut bridge = MemoryBridge::new();
    bridge.insert(MemoryItemRecord {
        item_id: "item-persist-1".to_string(),
        session_id: "sess-c".to_string(),
        text: "Critical persistent system state".to_string(),
        vector: vec![0.2, 0.4, 0.6, 0.8],
        tombstone: false,
        revision: 1,
        timestamp: 100.0,
    });
    bridge.insert(MemoryItemRecord {
        item_id: "item-persist-2".to_string(),
        session_id: "sess-c".to_string(),
        text: "Secondary item to be deleted before crash".to_string(),
        vector: vec![0.1, 0.3, 0.5, 0.7],
        tombstone: false,
        revision: 1,
        timestamp: 105.0,
    });

    // Delete item-persist-2
    bridge.delete("item-persist-2", 110.0).unwrap();

    // 1. Export snapshot representing cold storage / disk state
    let snapshot = bridge.export_snapshot();
    assert!(!snapshot.is_empty());

    // 2. Simulate process crash / clean new memory instance
    drop(bridge);

    // 3. Re-initialize memory bridge from cold snapshot
    let recovered = MemoryBridge::import_snapshot(&snapshot).expect("Crash recovery should succeed");
    assert_eq!(recovered.count_active(), 1);

    let active_item = recovered.get("item-persist-1").expect("Item 1 must survive crash recovery");
    assert_eq!(active_item.text, "Critical persistent system state");
    assert!(!active_item.tombstone);

    let deleted_item = recovered.get("item-persist-2").expect("Item 2 must exist in tombstoned state");
    assert!(deleted_item.tombstone);
}
