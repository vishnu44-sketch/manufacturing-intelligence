// A fake fetch for the tests: answers by address (a reply, or a function of the request for replies
// that change, e.g. the chat list after a delete), and keeps every call (no server, no AI).
import { vi } from 'vitest'

export type Reply = { status?: number; body: unknown; headers?: Record<string, string> }
export type Replies = Record<string, Reply | ((init?: RequestInit) => Reply)>

export function fakeFetch(replies: Replies) {
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    const found = replies[url]
    const reply = typeof found === 'function' ? found(init) : found
    if (!reply) return new Response(JSON.stringify({ detail: 'Not found.' }), { status: 404 })
    // a Blob (a file) or a ReadableStream (a streamed answer) goes as it is; anything else as JSON
    const body = reply.body instanceof Blob || reply.body instanceof ReadableStream ? reply.body : JSON.stringify(reply.body)
    return new Response(body, {
      status: reply.status ?? 200,
      headers: { 'Content-Type': 'application/json', ...reply.headers },
    })
  })
  vi.stubGlobal('fetch', fetch)
  return fetch
}

/** The calls made to one address with one method, with their JSON bodies. */
export function callsTo(fetch: ReturnType<typeof fakeFetch>, url: string, method = 'POST') {
  return fetch.mock.calls
    .filter(([u, init]) => u === url && (init?.method ?? 'GET') === method)
    .map(([, init]) => (init?.body ? JSON.parse(String(init.body)) : undefined))
}
