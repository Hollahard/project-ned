//! Hermes Native Memory Bridge & Mutation Router.
//!
//! Provides:
//! - Canonical session memory mutation paths (delete, rewind, replace, undo)
//! - Stale-result fencing: tombstoned or rewound entries are strictly excluded at query boundary
//! - Cold crash recovery: deterministic serialization & state restoration across restarts
//! - Fast in-memory KNN vector recall with sub-millisecond retrieval latency

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct MemoryItemRecord {
    pub item_id: String,
    pub session_id: String,
    pub text: String,
    pub vector: Vec<f32>,
    pub tombstone: bool,
    pub revision: u32,
    pub timestamp: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum MutationKind {
    Delete,
    Rewind,
    Replace,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct MutationRecord {
    pub mutation_id: String,
    pub kind: MutationKind,
    pub target_id: String,
    pub previous_state: Option<MemoryItemRecord>,
    pub timestamp: f64,
}

#[derive(Debug, Default, Serialize, Deserialize)]
pub struct MemoryBridge {
    items: HashMap<String, MemoryItemRecord>,
    mutation_history: Vec<MutationRecord>,
}

impl MemoryBridge {
    pub fn new() -> Self {
        Self {
            items: HashMap::new(),
            mutation_history: Vec::new(),
        }
    }

    pub fn insert(&mut self, item: MemoryItemRecord) {
        self.items.insert(item.item_id.clone(), item);
    }

    pub fn get(&self, item_id: &str) -> Option<&MemoryItemRecord> {
        self.items.get(item_id)
    }

    pub fn count_active(&self) -> usize {
        self.items.values().filter(|i| !i.tombstone).count()
    }

    /// memory.delete: Tomstones the target item, fences future recall, records undo stack.
    pub fn delete(&mut self, item_id: &str, timestamp: f64) -> Result<String, String> {
        let item = self.items.get_mut(item_id).ok_or_else(|| "Item not found".to_string())?;
        if item.tombstone {
            return Ok("Already deleted".to_string());
        }

        let previous = item.clone();
        item.tombstone = true;
        item.revision += 1;

        let mutation_id = format!("mut-del-{}", self.mutation_history.len() + 1);
        self.mutation_history.push(MutationRecord {
            mutation_id: mutation_id.clone(),
            kind: MutationKind::Delete,
            target_id: item_id.to_string(),
            previous_state: Some(previous),
            timestamp,
        });

        Ok(mutation_id)
    }

    /// memory.rewind: Tomstones items in session newer than valid_until_ts.
    pub fn rewind(&mut self, session_id: &str, valid_until_ts: f64, current_ts: f64) -> Result<usize, String> {
        let mut affected = 0;
        let mut rewound_previous = Vec::new();

        for item in self.items.values_mut() {
            if item.session_id == session_id && !item.tombstone && item.timestamp > valid_until_ts {
                rewound_previous.push(item.clone());
                item.tombstone = true;
                item.revision += 1;
                affected += 1;
            }
        }

        for prev in rewound_previous {
            self.mutation_history.push(MutationRecord {
                mutation_id: format!("mut-rew-{}", self.mutation_history.len() + 1),
                kind: MutationKind::Rewind,
                target_id: prev.item_id.clone(),
                previous_state: Some(prev),
                timestamp: current_ts,
            });
        }

        Ok(affected)
    }

    /// memory.replace: Atomically updates text and embedding vector, records undo state.
    pub fn replace(
        &mut self,
        item_id: &str,
        new_text: String,
        new_vec: Vec<f32>,
        timestamp: f64,
    ) -> Result<String, String> {
        let item = self.items.get_mut(item_id).ok_or_else(|| "Item not found".to_string())?;
        let previous = item.clone();

        item.text = new_text;
        item.vector = new_vec;
        item.revision += 1;
        item.tombstone = false;

        let mutation_id = format!("mut-rep-{}", self.mutation_history.len() + 1);
        self.mutation_history.push(MutationRecord {
            mutation_id: mutation_id.clone(),
            kind: MutationKind::Replace,
            target_id: item_id.to_string(),
            previous_state: Some(previous),
            timestamp,
        });

        Ok(mutation_id)
    }

    /// memory.undo: Inverts the most recent mutation, restoring previous state.
    pub fn undo(&mut self) -> Result<String, String> {
        let last_mutation = self.mutation_history.pop().ok_or_else(|| "No mutations to undo".to_string())?;
        if let Some(prev) = last_mutation.previous_state {
            let target_id = prev.item_id.clone();
            self.items.insert(target_id, prev);
            Ok(last_mutation.mutation_id)
        } else {
            Err("No previous state stored for mutation".to_string())
        }
    }

    /// KNN cosine similarity vector search with Stale-Result Fencing (tombstoned items omitted).
    pub fn search_knn(&self, query_vec: &[f32], top_k: usize, min_score: f32) -> Vec<(MemoryItemRecord, f32)> {
        let mut candidates = Vec::new();

        for item in self.items.values() {
            // STALE-RESULT FENCE: Tombstoned items are NEVER returned
            if item.tombstone {
                continue;
            }

            let score = cosine_similarity(query_vec, &item.vector);
            if score >= min_score {
                candidates.push((item.clone(), score));
            }
        }

        candidates.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
        candidates.truncate(top_k);
        candidates
    }

    /// Cold Crash Recovery: Exports full durable snapshot to JSON.
    pub fn export_snapshot(&self) -> String {
        serde_json::to_string(self).unwrap_or_default()
    }

    /// Cold Crash Recovery: Restores full durable state from JSON.
    pub fn import_snapshot(json_data: &str) -> Result<Self, String> {
        serde_json::from_str(json_data).map_err(|e| format!("Failed to restore snapshot: {}", e))
    }
}

pub fn cosine_similarity(v1: &[f32], v2: &[f32]) -> f32 {
    if v1.len() != v2.len() || v1.is_empty() {
        return 0.0;
    }
    let mut dot = 0.0;
    let mut norm1 = 0.0;
    let mut norm2 = 0.0;
    for (a, b) in v1.iter().zip(v2.iter()) {
        dot += a * b;
        norm1 += a * a;
        norm2 += b * b;
    }
    if norm1 <= 0.0 || norm2 <= 0.0 {
        return 0.0;
    }
    dot / (norm1.sqrt() * norm2.sqrt())
}
