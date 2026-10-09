use hermes_memory_bridge::{MemoryBridge, MemoryItemRecord};

#[test]
fn test_mutation_delete_and_undo() {
    let mut bridge = MemoryBridge::new();
    let item = MemoryItemRecord {
        item_id: "item-1".to_string(),
        session_id: "sess-a".to_string(),
        text: "Fact about project architecture".to_string(),
        vector: vec![0.5, 0.5, 0.5, 0.5],
        tombstone: false,
        revision: 1,
        timestamp: 100.0,
    };
    bridge.insert(item);
    assert_eq!(bridge.count_active(), 1);

    // 1. Delete
    let mut_id = bridge.delete("item-1", 105.0).expect("Delete should succeed");
    assert!(mut_id.starts_with("mut-del-"));
    assert_eq!(bridge.count_active(), 0);
    assert!(bridge.get("item-1").unwrap().tombstone);

    // 2. Undo delete
    let undone_id = bridge.undo().expect("Undo should succeed");
    assert_eq!(undone_id, mut_id);
    assert_eq!(bridge.count_active(), 1);
    assert!(!bridge.get("item-1").unwrap().tombstone);
}

#[test]
fn test_mutation_replace_and_undo() {
    let mut bridge = MemoryBridge::new();
    let item = MemoryItemRecord {
        item_id: "item-2".to_string(),
        session_id: "sess-a".to_string(),
        text: "Initial text version".to_string(),
        vector: vec![1.0, 0.0, 0.0, 0.0],
        tombstone: false,
        revision: 1,
        timestamp: 100.0,
    };
    bridge.insert(item);

    // Replace
    let rep_id = bridge.replace("item-2", "Updated text version".to_string(), vec![0.0, 1.0, 0.0, 0.0], 110.0)
        .expect("Replace should succeed");
    assert!(rep_id.starts_with("mut-rep-"));

    let updated = bridge.get("item-2").unwrap();
    assert_eq!(updated.text, "Updated text version");
    assert_eq!(updated.revision, 2);

    // Undo replace
    bridge.undo().expect("Undo should revert replace");
    let reverted = bridge.get("item-2").unwrap();
    assert_eq!(reverted.text, "Initial text version");
    assert_eq!(reverted.revision, 1);
}

#[test]
fn test_mutation_rewind_session() {
    let mut bridge = MemoryBridge::new();
    for i in 1..=4 {
        bridge.insert(MemoryItemRecord {
            item_id: format!("item-{}", i),
            session_id: "sess-b".to_string(),
            text: format!("Message {}", i),
            vector: vec![0.1 * i as f32; 4],
            tombstone: false,
            revision: 1,
            timestamp: 100.0 + (i as f64 * 10.0), // 110, 120, 130, 140
        });
    }
    assert_eq!(bridge.count_active(), 4);

    // Rewind session back to t=125.0 (items 3 and 4 should be tombstoned)
    let affected = bridge.rewind("sess-b", 125.0, 150.0).expect("Rewind should succeed");
    assert_eq!(affected, 2);
    assert_eq!(bridge.count_active(), 2);

    assert!(!bridge.get("item-1").unwrap().tombstone);
    assert!(!bridge.get("item-2").unwrap().tombstone);
    assert!(bridge.get("item-3").unwrap().tombstone);
    assert!(bridge.get("item-4").unwrap().tombstone);
}
