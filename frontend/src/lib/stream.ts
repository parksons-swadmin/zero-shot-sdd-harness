// SSE consumer for POST /sessions/{session_id}/messages/stream (Phase 3c).
//
// The browser `EventSource` API is GET-only and cannot send a request body, but
// the run needs the question in a POST body and *starts* the run — so we consume
// the SSE wire format (`event: <type>\ndata: <one-line JSON>\n\n`) manually over
// a `fetch()` + `ReadableStream` reader, splitting frames on the blank-line
// separator. See spec/api.md and spec/roadmap.md Phase 3c design decision #1.

import type {
  AnswerChunkEvent,
  StepEvent,
  StreamErrorEvent,
  StreamResultEvent,
} from './types'

export interface StreamCallbacks {
  onStep?: (event: StepEvent) => void
  onChunk?: (event: AnswerChunkEvent) => void
  onResult?: (event: StreamResultEvent) => void | Promise<void>
  onError?: (event: StreamErrorEvent) => void
  onDone?: () => void
}

export interface StreamOutcome {
  // Whether the SSE stream actually opened (200 + a readable body). When false,
  // `httpStatus` carries the pre-stream JSON error code (404/409/422) so the
  // caller can fall back to the non-streaming POST or surface the error.
  ok: boolean
  httpStatus: number
  // How many well-formed SSE events were dispatched — lets the caller decide to
  // fall back to the non-streaming POST if the stream produced nothing usable.
  eventsReceived: number
}

export async function streamAsk(
  sessionId: string,
  question: string,
  callbacks: StreamCallbacks,
  signal?: AbortSignal,
): Promise<StreamOutcome> {
  const res = await fetch(`/sessions/${sessionId}/messages/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ question }),
    signal,
  })

  // 404 (unknown session), 409 (busy) and 422 (empty question) come back as a
  // normal JSON error BEFORE the stream begins — no readable event body.
  if (!res.ok || !res.body) {
    return { ok: false, httpStatus: res.status, eventsReceived: 0 }
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let eventsReceived = 0

  const dispatch = async (rawFrame: string): Promise<void> => {
    let eventType = 'message'
    const dataLines: string[] = []
    for (const line of rawFrame.split('\n')) {
      if (line.startsWith('event:')) {
        eventType = line.slice('event:'.length).trim()
      } else if (line.startsWith('data:')) {
        dataLines.push(line.slice('data:'.length).replace(/^ /, ''))
      }
    }
    if (dataLines.length === 0) return

    let payload: unknown
    try {
      payload = JSON.parse(dataLines.join('\n'))
    } catch {
      return // ignore malformed frames rather than crash the whole read
    }
    eventsReceived += 1

    switch (eventType) {
      case 'step':
        callbacks.onStep?.(payload as StepEvent)
        break
      case 'answer_chunk':
        callbacks.onChunk?.(payload as AnswerChunkEvent)
        break
      case 'result':
        await callbacks.onResult?.(payload as StreamResultEvent)
        break
      case 'error':
        callbacks.onError?.(payload as StreamErrorEvent)
        break
      case 'done':
        callbacks.onDone?.()
        break
      default:
        break
    }
  }

  // Read the byte stream, splitting complete `\n\n`-delimited SSE frames as they
  // arrive so `answer_chunk`s render progressively.
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    let sepIndex: number
    while ((sepIndex = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, sepIndex)
      buffer = buffer.slice(sepIndex + 2)
      if (frame.trim()) await dispatch(frame)
    }
  }

  // Flush any trailing frame not terminated by a blank line.
  buffer += decoder.decode()
  if (buffer.trim()) await dispatch(buffer)

  return { ok: true, httpStatus: res.status, eventsReceived }
}
