/**
 * Desktop UI GPU Resource Authority & Gaming Mode Latch Client.
 *
 * Implements:
 * - Admission barrier returning GATEWAY_BUSY_GAMING_MODE when Gaming Mode is engaged
 * - Worker cancellation & drain protocol evacuating GPU memory to 0 VRAM baseline
 * - RTX 5090 (32 GiB) allocation accounting across LLM, draft, vision, embeddings, audio, and profiler
 * - Cold crash recovery state synchronization
 */

export const GATEWAY_BUSY_GAMING_MODE = 'GATEWAY_BUSY_GAMING_MODE';
export const RTX_5090_TOTAL_VRAM_BYTES = 34_359_738_368; // 32 GiB

export type GpuWorkerType =
  | 'PrimaryLlm'
  | 'DraftModel'
  | 'Vision'
  | 'Embeddings'
  | 'SpeechAudio'
  | 'Profiler';

export type GamingModeState = 'Inactive' | 'Transitioning' | 'Active';

export interface GpuLease {
  lease_id: string;
  worker: GpuWorkerType;
  vram_allocated_bytes: number;
  generation: number;
  active: boolean;
}

export interface GamingModeReport {
  vram_freed_bytes: number;
  cancelled_leases: number;
  elapsed_ms: number;
}

export class GpuAdmissionError extends Error {
  public readonly code: string;
  public readonly worker?: GpuWorkerType;

  constructor(message: string, code: string = GATEWAY_BUSY_GAMING_MODE, worker?: GpuWorkerType) {
    super(message);
    this.name = 'GpuAdmissionError';
    this.code = code;
    this.worker = worker;
  }
}

export interface CoordinatorSnapshot {
  total_vram_bytes: number;
  allocated_vram_bytes: number;
  gaming_mode: GamingModeState;
  generation: number;
  leases: Record<string, GpuLease>;
}

export class GpuCoordinatorClient {
  private totalVramBytes: number;
  private allocatedVramBytes: number = 0;
  private gamingMode: GamingModeState = 'Inactive';
  private generation: number = 1;
  private readonly leases = new Map<string, GpuLease>();
  private readonly cancellationListeners = new Set<(lease: GpuLease) => void>();

  constructor(totalVramBytes: number = RTX_5090_TOTAL_VRAM_BYTES) {
    this.totalVramBytes = totalVramBytes;
  }

  public isGamingModeActive(): boolean {
    return this.gamingMode === 'Active' || this.gamingMode === 'Transitioning';
  }

  public getGamingModeState(): GamingModeState {
    return this.gamingMode;
  }

  public getAvailableVramBytes(): number {
    return Math.max(0, this.totalVramBytes - this.allocatedVramBytes);
  }

  public getAllocatedVramBytes(): number {
    return this.allocatedVramBytes;
  }

  public getTotalVramBytes(): number {
    return this.totalVramBytes;
  }

  public onCancellation(listener: (lease: GpuLease) => void): () => void {
    this.cancellationListeners.add(listener);
    return () => {
      this.cancellationListeners.delete(listener);
    };
  }

  /**
   * Requests admission for a GPU-consuming worker.
   * Throws GpuAdmissionError with GATEWAY_BUSY_GAMING_MODE if Gaming Mode is engaged.
   */
  public requestAdmission(worker: GpuWorkerType, requiredVramBytes: number): GpuLease {
    if (this.isGamingModeActive()) {
      throw new GpuAdmissionError(
        `${GATEWAY_BUSY_GAMING_MODE}: Admission barrier active; GPU worker ${worker} rejected`,
        GATEWAY_BUSY_GAMING_MODE,
        worker
      );
    }

    if (requiredVramBytes > this.getAvailableVramBytes()) {
      throw new GpuAdmissionError(
        `Insufficient VRAM available for worker ${worker} (requested: ${requiredVramBytes}, available: ${this.getAvailableVramBytes()})`,
        'INSUFFICIENT_VRAM',
        worker
      );
    }

    this.generation += 1;
    this.allocatedVramBytes += requiredVramBytes;

    const leaseId = `lease-${this.generation}-${this.leases.size + 1}`;
    const lease: GpuLease = {
      lease_id: leaseId,
      worker,
      vram_allocated_bytes: requiredVramBytes,
      generation: this.generation,
      active: true,
    };

    this.leases.set(leaseId, lease);
    return { ...lease };
  }

  public releaseLease(leaseId: string): void {
    const lease = this.leases.get(leaseId);
    if (!lease) {
      throw new Error(`Lease ${leaseId} not found`);
    }

    if (lease.active) {
      lease.active = false;
      this.allocatedVramBytes = Math.max(0, this.allocatedVramBytes - lease.vram_allocated_bytes);
    }
  }

  /**
   * Activates Gaming Mode: halts all active workers, notifies listeners with cancellation frames,
   * drains memory to 0 bytes baseline.
   */
  public activateGamingMode(): GamingModeReport {
    const startTime = performance.now();
    this.gamingMode = 'Transitioning';

    let cancelledCount = 0;
    const freedBytes = this.allocatedVramBytes;

    for (const lease of this.leases.values()) {
      if (lease.active) {
        lease.active = false;
        cancelledCount += 1;
        for (const listener of this.cancellationListeners) {
          try {
            listener({ ...lease });
          } catch {
            // Listener errors do not block coordinator drain
          }
        }
      }
    }

    this.allocatedVramBytes = 0;
    this.generation += 1;
    this.gamingMode = 'Active';

    const elapsedMs = performance.now() - startTime;
    return {
      vram_freed_bytes: freedBytes,
      cancelled_leases: cancelledCount,
      elapsed_ms: elapsedMs,
    };
  }

  public deactivateGamingMode(): void {
    this.gamingMode = 'Inactive';
    this.generation += 1;
  }

  public exportSnapshot(): string {
    const leasesObj: Record<string, GpuLease> = {};
    for (const [k, v] of this.leases.entries()) {
      leasesObj[k] = { ...v };
    }
    const snapshot: CoordinatorSnapshot = {
      total_vram_bytes: this.totalVramBytes,
      allocated_vram_bytes: this.allocatedVramBytes,
      gaming_mode: this.gamingMode,
      generation: this.generation,
      leases: leasesObj,
    };
    return JSON.stringify(snapshot);
  }

  public importSnapshot(snapshotJson: string): void {
    const snapshot = JSON.parse(snapshotJson) as CoordinatorSnapshot;
    this.totalVramBytes = snapshot.total_vram_bytes;
    this.allocatedVramBytes = snapshot.allocated_vram_bytes;
    this.gamingMode = snapshot.gaming_mode;
    this.generation = snapshot.generation;
    this.leases.clear();
    for (const [k, v] of Object.entries(snapshot.leases)) {
      this.leases.set(k, { ...v });
    }
  }
}
