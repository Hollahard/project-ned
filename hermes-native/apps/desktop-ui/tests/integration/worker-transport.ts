import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import type { ControlTransport } from '@native/control-client.ts'

/** Test bridge only: production uses Rust process ownership and framed IPC. */
export class WorkerTransport implements ControlTransport {
  private child: ChildProcessWithoutNullStreams
  private buffered = Buffer.alloc(0)
  private nextId = 0
  private pending = new Map<string, { resolve: (value: any) => void; reject: (value: unknown) => void; timer: ReturnType<typeof setTimeout> }>()
  private readyResolve!: () => void
  private readyReject!: (error: Error) => void
  private readyTimer: ReturnType<typeof setTimeout>
  readonly ready = new Promise<void>((resolve, reject) => { this.readyResolve = resolve; this.readyReject = reject })
  readonly exited: Promise<number | null>
  readonly calls: { operation: string; payload: any }[] = []
  stderr = ''

  constructor(readonly state: string) {
    const env: NodeJS.ProcessEnv = {}
    for (const key of ['SystemRoot', 'WINDIR']) if (process.env[key]) env[key] = process.env[key]
    this.child = spawn(process.env.HERMES_BASE_PYTHON!, [
      '-I', '-S', '-B', '-X', 'utf8', path.join(process.env.HERMES_CONTROL_WORKER_ROOT!, 'bootstrap.py'),
      '--inference-src', process.env.HERMES_INFERENCE_SRC!, '--state-dir', state,
    ], { cwd: state, env, windowsHide: true, stdio: 'pipe' })
    this.exited = new Promise(resolve => this.child.once('exit', code => resolve(code)))
    this.child.once('error', error => this.fail(error))
    this.child.once('close', code => this.fail(new Error(`Fixture worker exited (${code}): ${this.stderr}`)))
    this.child.stdout.on('data', chunk => this.read(chunk))
    this.child.stderr.on('data', chunk => { this.stderr = (this.stderr + chunk.toString('utf8')).slice(-4096) })
    this.readyTimer = setTimeout(() => { this.fail(new Error('Fixture worker readiness timeout')); this.child.kill() }, 5000)
  }

  static createState(): string {
    return fs.mkdtempSync(path.join(process.env.HERMES_UI_TEST_ROOT!, '.runs', 'state-'))
  }

  private fail(error: Error) {
    clearTimeout(this.readyTimer)
    this.readyReject(error)
    for (const pending of this.pending.values()) { clearTimeout(pending.timer); pending.reject(error) }
    this.pending.clear()
  }

  private read(chunk: Buffer) {
    this.buffered = Buffer.concat([this.buffered, chunk])
    if (this.buffered.length > 131072) { this.fail(new Error('Fixture response buffer exceeded')); this.child.kill(); return }
    let newline: number
    while ((newline = this.buffered.indexOf(10)) >= 0) {
      const line = this.buffered.subarray(0, newline)
      this.buffered = this.buffered.subarray(newline + 1)
      if (line.length > 65535 || line.includes(13)) { this.fail(new Error('Invalid worker frame')); this.child.kill(); return }
      let frame: any
      try { frame = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(line)) }
      catch { this.fail(new Error('Invalid worker JSON')); this.child.kill(); return }
      if (frame.type === 'ready') {
        if (JSON.stringify(frame) !== JSON.stringify({ type: 'ready', protocol: 'hermes-control-v1', service: 'hermes-control-worker', runtime_attached: false })) {
          this.fail(new Error('Unexpected worker hello')); this.child.kill(); return
        }
        clearTimeout(this.readyTimer); this.readyResolve(); continue
      }
      const pending = this.pending.get(frame.id)
      if (!pending) { this.fail(new Error('Unexpected fixture response id')); this.child.kill(); return }
      this.pending.delete(frame.id); clearTimeout(pending.timer)
      if (frame.error) pending.reject(frame.error); else pending.resolve(frame.result)
    }
  }

  async control<T>(operation: string, payload: object): Promise<T> {
    await this.ready
    const id = `fixture-${++this.nextId}`
    this.calls.push({ operation, payload: structuredClone(payload) })
    const frame = Buffer.from(JSON.stringify({ id, method: operation, params: payload }) + '\n', 'utf8')
    if (frame.length > 65536) throw new Error('Fixture request exceeds maximum frame')
    return await new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error('Fixture worker timeout')); this.child.kill() }, 5000)
      this.pending.set(id, { resolve, reject, timer })
      this.child.stdin.write(frame, error => { if (error) this.fail(error) })
    })
  }

  async close() {
    const timeout = setTimeout(() => this.child.kill(), 5000)
    if (this.child.exitCode === null) {
      try { await this.control('service.shutdown', {}) }
      catch { this.child.stdin.end() }
    }
    const code = await this.exited
    clearTimeout(timeout)
    return code
  }
}
