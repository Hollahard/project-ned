/**
 * Desktop UI Memory Bridge Client & Mutation Router.
 *
 * Implements:
 * - Canonical session memory mutation paths (delete, rewind, replace, undo)
 * - Stale-result fencing (filtering tombstoned items out of query results)
 * - Cold crash recovery state synchronization
 * - Local KNN cosine similarity search with zero external network calls
 */

export interface MemoryItem {
  item_id: string;
  session_id: string;
  text: string;
  vector: number[];
  tombstone: boolean;
  revision: number;
  timestamp: number;
}

export type MutationType = 'delete' | 'rewind' | 'replace' | 'undo';

export interface MemoryMutationResult {
  mutation_id: string;
  type: MutationType;
  target_id: string;
  success: boolean;
}

export interface MemorySearchResult {
  item_id: string;
  text: string;
  score: number;
  session_id: string;
}

export function cosineSimilarity(v1: number[], v2: number[]): number {
  if (v1.length !== v2.length || v1.length === 0) return 0;
  let dot = 0;
  let norm1 = 0;
  let norm2 = 0;
  for (let i = 0; i < v1.length; i++) {
    dot += v1[i] * v2[i];
    norm1 += v1[i] * v1[i];
    norm2 += v2[i] * v2[i];
  }
  if (norm1 <= 0 || norm2 <= 0) return 0;
  return dot / (Math.sqrt(norm1) * Math.sqrt(norm2));
}

export class MemoryBridgeClient {
  private readonly items = new Map<string, MemoryItem>();
  private readonly undoStack: MemoryItem[] = [];

  public insert(item: MemoryItem): void {
    this.items.set(item.item_id, { ...item });
  }

  public get(itemId: string): MemoryItem | undefined {
    return this.items.get(itemId);
  }

  public countActive(): number {
    let count = 0;
    for (const item of this.items.values()) {
      if (!item.tombstone) count++;
    }
    return count;
  }

  public async deleteMemory(itemId: string, timestamp: number = Date.now()): Promise<MemoryMutationResult> {
    const item = this.items.get(itemId);
    if (!item) {
      throw new Error(`Item ${itemId} not found`);
    }

    this.undoStack.push({ ...item });
    item.tombstone = true;
    item.revision += 1;

    return {
      mutation_id: `mut-del-${this.undoStack.length}`,
      type: 'delete',
      target_id: itemId,
      success: true,
    };
  }

  public async rewindMemory(sessionId: string, validUntilTs: number): Promise<number> {
    let affected = 0;
    for (const item of this.items.values()) {
      if (item.session_id === sessionId && !item.tombstone && item.timestamp > validUntilTs) {
        this.undoStack.push({ ...item });
        item.tombstone = true;
        item.revision += 1;
        affected++;
      }
    }
    return affected;
  }

  public async replaceMemory(itemId: string, newText: string, newVector: number[]): Promise<MemoryMutationResult> {
    const item = this.items.get(itemId);
    if (!item) {
      throw new Error(`Item ${itemId} not found`);
    }

    this.undoStack.push({ ...item });
    item.text = newText;
    item.vector = newVector;
    item.revision += 1;
    item.tombstone = false;

    return {
      mutation_id: `mut-rep-${this.undoStack.length}`,
      type: 'replace',
      target_id: itemId,
      success: true,
    };
  }

  public async undoMemory(): Promise<MemoryMutationResult> {
    const previous = this.undoStack.pop();
    if (!previous) {
      throw new Error('No mutations to undo');
    }

    this.items.set(previous.item_id, previous);
    return {
      mutation_id: `undo-${previous.item_id}`,
      type: 'undo',
      target_id: previous.item_id,
      success: true,
    };
  }

  public async searchMemory(queryVector: number[], topK: number = 5, minScore: number = 0.0): Promise<MemorySearchResult[]> {
    const candidates: MemorySearchResult[] = [];

    for (const item of this.items.values()) {
      // Stale-result fence: tombstoned items are strictly omitted
      if (item.tombstone) continue;

      const score = cosineSimilarity(queryVector, item.vector);
      if (score >= minScore) {
        candidates.push({
          item_id: item.item_id,
          text: item.text,
          score,
          session_id: item.session_id,
        });
      }
    }

    candidates.sort((a, b) => b.score - a.score);
    return candidates.slice(0, topK);
  }

  public exportSnapshot(): string {
    return JSON.stringify(Array.from(this.items.values()));
  }

  public importSnapshot(jsonString: string): void {
    const items: MemoryItem[] = JSON.parse(jsonString);
    this.items.clear();
    for (const item of items) {
      this.items.set(item.item_id, item);
    }
  }
}
