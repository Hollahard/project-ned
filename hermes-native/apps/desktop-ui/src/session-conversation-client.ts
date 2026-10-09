/** Session conversation client, streaming delta state handler, and ambiguity defense. */

export type ConversationState = 'idle' | 'connecting' | 'streaming' | 'awaiting_tool' | 'error'
export type SubmitStatus = 'idle' | 'in_flight' | 'uncertain' | 'completed' | 'interrupted' | 'error'

export interface ToolCall {
  id: string
  name: string
  arguments: string
}

export interface Message {
  role: 'user' | 'assistant' | 'tool'
  content: string
  toolCalls?: ToolCall[]
  toolCallId?: string
}

export interface StreamingTextDelta {
  kind: 'text_delta'
  chunkIndex: number
  text: string
}

export interface StreamingToolCall {
  kind: 'tool_call'
  toolCall: ToolCall
}

export interface StreamingComplete {
  kind: 'message_complete'
  finishReason: 'stop' | 'interrupted' | 'tool_call'
  fullText: string
}

export type StreamingEvent = StreamingTextDelta | StreamingToolCall | StreamingComplete

export interface TransportSender {
  sendRpc(method: string, params: Record<string, unknown>): Promise<unknown>
}

export class UncertainSubmitError extends Error {
  readonly code = 'UNCERTAIN_SUBMIT_REQUIRES_MANUAL_RETRY'
  constructor(sessionId: string) {
    super(`Session ${sessionId} is in an UNCERTAIN state due to transport disruption. Automatic retry is strictly prohibited; manual re-submission is required.`)
    this.name = 'UncertainSubmitError'
  }
}

export class ProfileMismatchError extends Error {
  readonly code = 'PROFILE_MISMATCH'
  constructor(sessionId: string, expected: string, actual: string) {
    super(`Profile mismatch for session ${sessionId}: expected ${expected}, got ${actual}`)
    this.name = 'ProfileMismatchError'
  }
}

export class SessionConversationClient {
  readonly sessionId: string
  readonly profileId: string
  #state: ConversationState = 'idle'
  #submitStatus: SubmitStatus = 'idle'
  #uncertainLatch = false
  #history: Message[] = []
  #assembledText = ''
  #expectedChunkIndex = 0
  #bufferedChunks = new Map<number, string>()
  #pendingTools = new Map<string, ToolCall>()
  #transport?: TransportSender
  #activeAbortController?: AbortController

  constructor(sessionId: string, profileId: string, transport?: TransportSender) {
    this.sessionId = sessionId
    this.profileId = profileId
    this.#transport = transport
  }

  get state(): ConversationState {
    return this.#state
  }

  get submitStatus(): SubmitStatus {
    return this.#submitStatus
  }

  get history(): readonly Message[] {
    return [...this.#history]
  }

  get assembledText(): string {
    return this.#assembledText
  }

  get isUncertain(): boolean {
    return this.#uncertainLatch
  }

  /** Submits a prompt with transport ambiguity fencing and local AbortSignal linkage. */
  async submitPrompt(
    text: string,
    options?: { signal?: AbortSignal; isManualRetry?: boolean }
  ): Promise<string> {
    if (this.#uncertainLatch && !options?.isManualRetry) {
      throw new UncertainSubmitError(this.sessionId)
    }

    if (this.#state === 'connecting' || this.#state === 'streaming' || this.#state === 'awaiting_tool') {
      throw new Error(`Session ${this.sessionId} is busy.`)
    }

    this.#uncertainLatch = false
    this.#state = 'connecting'
    this.#submitStatus = 'in_flight'
    this.#assembledText = ''
    this.#expectedChunkIndex = 0
    this.#bufferedChunks.clear()
    this.#pendingTools.clear()

    this.#history.push({ role: 'user', content: text })

    const abortController = new AbortController()
    this.#activeAbortController = abortController

    if (options?.signal) {
      if (options.signal.aborted) {
        await this.interrupt()
        throw new DOMException('Prompt submission aborted', 'AbortError')
      }
      options.signal.addEventListener('abort', () => {
        void this.interrupt()
      }, { once: true })
    }

    if (this.#transport) {
      try {
        await this.#transport.sendRpc('prompt.submit', {
          session_id: this.sessionId,
          profile_id: this.profileId,
          text,
        })
      } catch (err) {
        this.onTransportDrop()
        throw err
      }
    }

    return text
  }

  /** Manual re-submission following an uncertain transport drop. */
  async resubmit(text: string, options?: { signal?: AbortSignal }): Promise<string> {
    return this.submitPrompt(text, { ...options, isManualRetry: true })
  }

  /** Called when network connection drops or times out while submit is in flight. */
  onTransportDrop(): void {
    if (this.#submitStatus === 'in_flight') {
      this.#submitStatus = 'uncertain'
      this.#uncertainLatch = true
      this.#state = 'idle'
    }
  }

  /** Ingests streaming delta text chunks in strictly verified sequence order. */
  onTextDelta(chunkIndex: number, text: string): string {
    if (this.#state === 'connecting' || this.#state === 'streaming') {
      this.#state = 'streaming'
    }

    if (chunkIndex < this.#expectedChunkIndex) {
      return this.#assembledText
    }

    this.#bufferedChunks.set(chunkIndex, text)

    while (this.#bufferedChunks.has(this.#expectedChunkIndex)) {
      const next = this.#bufferedChunks.get(this.#expectedChunkIndex)!
      this.#bufferedChunks.delete(this.#expectedChunkIndex)
      this.#assembledText += next
      this.#expectedChunkIndex++
    }

    return this.#assembledText
  }

  /** Ingests tool call from model stream; moves state machine to awaiting_tool. */
  onToolCall(toolCall: ToolCall): void {
    this.#state = 'awaiting_tool'
    this.#pendingTools.set(toolCall.id, toolCall)
  }

  /** Ingests tool execution result; moves state back to streaming. */
  onToolResult(toolCallId: string, output: string): void {
    const call = this.#pendingTools.get(toolCallId)
    if (!call) throw new Error(`Tool call ${toolCallId} not found`)

    this.#pendingTools.delete(toolCallId)
    this.#history.push({
      role: 'assistant',
      content: '',
      toolCalls: [call],
    })
    this.#history.push({
      role: 'tool',
      content: output,
      toolCallId,
    })

    if (this.#pendingTools.size === 0) {
      this.#state = 'streaming'
    }
  }

  /** Ingests message complete event; updates history and resets state machine to idle. */
  onMessageComplete(finishReason: 'stop' | 'interrupted' | 'tool_call'): string {
    const fullText = this.#assembledText
    if (fullText.length > 0) {
      this.#history.push({
        role: 'assistant',
        content: fullText,
      })
    }

    this.#state = 'idle'
    this.#submitStatus = finishReason === 'interrupted' ? 'interrupted' : 'completed'
    this.#bufferedChunks.clear()
    this.#pendingTools.clear()
    this.#activeAbortController = undefined

    return fullText
  }

  /** Executes session interruption, dispatches cancellation RPC, and clears tools. */
  async interrupt(): Promise<{ interrupted: boolean; partialText: string }> {
    if (this.#state === 'connecting' || this.#state === 'streaming' || this.#state === 'awaiting_tool') {
      const partialText = this.#assembledText
      this.#pendingTools.clear()

      if (partialText.length > 0) {
        this.#history.push({
          role: 'assistant',
          content: `${partialText} [interrupted]`,
        })
      }

      this.#state = 'idle'
      this.#submitStatus = 'interrupted'
      this.#bufferedChunks.clear()
      this.#activeAbortController?.abort()
      this.#activeAbortController = undefined

      if (this.#transport) {
        await this.#transport.sendRpc('session.interrupt', {
          session_id: this.sessionId,
          profile_id: this.profileId,
        }).catch(() => undefined)
      }

      return { interrupted: true, partialText }
    }

    return { interrupted: false, partialText: '' }
  }

  /** Verifies that a request belongs to the active profile ID, preventing cross-profile leakage. */
  verifyProfile(targetProfileId: string): void {
    if (targetProfileId !== this.profileId) {
      throw new ProfileMismatchError(this.sessionId, this.profileId, targetProfileId)
    }
  }
}
