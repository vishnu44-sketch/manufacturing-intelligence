// Talking to the Django JSON API (/api/...): the session cookie goes with every call, and every POST
// carries the CSRF token (Django's cookie) in the X-CSRFToken header. A 401 means "not signed in":
// the app then shows its Login page. A 403 on a staff page means "no access".
import type {
  AiChartReply, AskResponse, AuditData, AuditFilters, ChatDetail, ChatList, ChatSummary, DataTables, DocumentsData, EditResponse,
  GraphNodeReply, GraphSearchReply, GraphSimilarReply, HistoryPage, HomeData, Me, MemoryList, MemoryReply, PeopleList, PersonReply, Rows, SavedAnswer, StreamEvent,
} from './types'

// this app's own cookie name (nopsite/settings.py CSRF_COOKIE_NAME), then Django's default
const CSRF_COOKIES = ['asknop_csrftoken', 'csrftoken']

export class AuthError extends Error {}

export class ApiError extends Error {
  status: number
  errors: Record<string, string[]> // field -> messages (a form that did not pass its checks)
  constructor(status: number, message: string, errors: Record<string, string[]> = {}) {
    super(message)
    this.status = status
    this.errors = errors
  }
}

let lastToken = '' // the token the API last sent (used when the cookie cannot be read)
let onUnauthorized: (() => void) | null = null

/** The app sets this: it is called on every 401 (show the Login page). */
export function setUnauthorizedHandler(handler: (() => void) | null) {
  onUnauthorized = handler
}

function readCookie(name: string): string {
  for (const part of document.cookie ? document.cookie.split('; ') : []) {
    const at = part.indexOf('=')
    if (part.slice(0, at) === name) return decodeURIComponent(part.slice(at + 1))
  }
  return ''
}

export function csrfToken(): string {
  for (const name of CSRF_COOKIES) {
    const value = readCookie(name)
    if (value) return value
  }
  return lastToken
}

const UNREACHABLE = 'The server cannot be reached - check that Django is running.'

async function send(method: 'GET' | 'POST', url: string, body?: unknown, accept = 'application/json'): Promise<Response> {
  const headers: Record<string, string> = { Accept: accept }
  if (method === 'POST') {
    headers['Content-Type'] = 'application/json'
    headers['X-CSRFToken'] = csrfToken()
  }
  try {
    return await fetch(url, {
      method,
      credentials: 'include',
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, UNREACHABLE)
  }
}

/** Throws AuthError on a 401 (after telling the app) and ApiError on any other failure. */
function check(response: Response, data: unknown) {
  if (response.status === 401) {
    onUnauthorized?.()
    throw new AuthError('Please sign in.')
  }
  if (!response.ok) {
    const fields = data && typeof data === 'object' ? (data as { detail?: unknown; errors?: unknown }) : {}
    const detail = fields.detail ? String(fields.detail) : ''
    const errors = fields.errors && typeof fields.errors === 'object' ? (fields.errors as Record<string, string[]>) : {}
    throw new ApiError(response.status, detail || `The server answered ${response.status}.`, errors)
  }
}

async function request<T>(method: 'GET' | 'POST', url: string, body?: unknown): Promise<T> {
  const response = await send(method, url, body)
  let data: unknown = null
  try {
    data = await response.json()
  } catch {
    data = null // e.g. an HTML error page
  }
  if (data && typeof data === 'object' && 'csrfToken' in data) {
    lastToken = String((data as { csrfToken: unknown }).csrfToken)
  }
  check(response, data)
  return data as T
}

/** Makes sure the CSRF cookie is there before the first POST (Django sets it with the page too). */
export async function ensureCsrf(): Promise<void> {
  if (!csrfToken()) await request('GET', '/api/csrf')
}

/** A query string from the filled-in values ('' when none): {page: 2} -> '?page=2'. */
export function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

/** Downloads a file (the Excel of an answer) and saves it under the server's file name. A failure
 *  (e.g. MySQL is down) becomes an ApiError with the server's friendly message. */
export async function download(url: string): Promise<void> {
  const response = await send('GET', url, undefined, '*/*')
  if (!response.ok) {
    let data: unknown = null
    try {
      data = await response.json()
    } catch {
      data = null
    }
    check(response, data)
  }
  const blob = await response.blob()
  const name = /filename="([^"]+)"/.exec(response.headers.get('Content-Disposition') ?? '')?.[1] ?? 'download.xlsx'
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = name
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(link.href), 1000)
}

/** The streamed answer could not be used at all - nothing came back (e.g. a proxy, or a server without
 *  /api/ask/stream). The question is then asked the plain way (api.ask). */
export class StreamUnavailable extends Error {}

const STREAM_TYPE = 'application/x-ndjson'
const STREAM_LOST = 'The connection was lost while the answer was being written. It is saved - you can find it in History.'

/** Asks with the answer streamed (/api/ask/stream): onEvent gets each step and each piece of the answer as it
 *  comes, and the promise gives the same reply as api.ask. A refused question (400, 404 ...) and a sign-in
 *  problem fail as api.ask does; StreamUnavailable when no event came back at all. */
export async function askStream(question: string, chatId: number | null,
  onEvent: (event: StreamEvent) => void): Promise<AskResponse> {
  let response: Response
  try {
    response = await send('POST', '/api/ask/stream', { question, chat_id: chatId }, STREAM_TYPE)
  } catch {
    throw new StreamUnavailable('The stream could not be opened.')
  }
  const type = response.headers.get('Content-Type') ?? ''
  if (!type.includes(STREAM_TYPE) || !response.body) {
    if (type.includes('application/json') && ![404, 405].includes(response.status)) {
      let data: unknown = null
      try {
        data = await response.json()
      } catch {
        data = null
      }
      check(response, data) // the question's own problem (400, 401, 403 ...): shown as with api.ask
    }
    throw new StreamUnavailable(`The stream answered ${response.status} ${type}.`)
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let seen = false
  const handle = (line: string): AskResponse | null => {
    if (!line.trim()) return null
    let event: StreamEvent
    try {
      event = JSON.parse(line) as StreamEvent
    } catch {
      return null // not one of our lines
    }
    seen = true
    if (event.type === 'done') return { chat: event.chat, card: event.card }
    if (event.type === 'error') throw new ApiError(500, event.message)
    onEvent(event)
    return null
  }
  for (;;) {
    let chunk: ReadableStreamReadResult<Uint8Array>
    try {
      chunk = await reader.read()
    } catch {
      if (!seen) throw new StreamUnavailable('The stream broke before it started.')
      throw new ApiError(0, STREAM_LOST)
    }
    buffer += chunk.done ? decoder.decode() : decoder.decode(chunk.value, { stream: true })
    const lines = buffer.split('\n')
    buffer = chunk.done ? '' : lines.pop() ?? ''
    for (const line of lines) {
      const reply = handle(line)
      if (reply) return reply
    }
    if (chunk.done) break
  }
  if (!seen) throw new StreamUnavailable('The stream sent nothing.')
  throw new ApiError(0, STREAM_LOST)
}

export const api = {
  me: () => request<Me>('GET', '/api/me'),
  // the Home page: the KPI cards, the main tables, the connections and the user's usage (read-only, no AI call)
  home: () => request<HomeData>('GET', '/api/home'),
  login: async (username: string, password: string) => {
    await ensureCsrf()
    return request<{ username: string; is_staff: boolean }>('POST', '/api/login', { username, password })
  },
  logout: () => request<{ ok: boolean }>('POST', '/api/logout', {}),
  // chats
  chats: () => request<ChatList>('GET', '/api/chats'),
  chat: (id: number) => request<ChatDetail>('GET', `/api/chats/${id}`),
  renameChat: (id: number, title: string) =>
    request<{ chat: ChatSummary }>('POST', `/api/chats/${id}/rename`, { title }),
  removeChat: (id: number) => request<{ chat: ChatSummary; message: string }>('POST', `/api/chats/${id}/remove`, {}),
  restoreChat: (id: number) => request<{ chat: ChatSummary }>('POST', `/api/chats/${id}/restore`, {}),
  deleteChat: (id: number) => request<{ deleted: number; message: string }>('POST', `/api/chats/${id}/delete`, {}),
  // questions
  ask: (question: string, chatId: number | null) =>
    request<AskResponse>('POST', '/api/ask', { question, chat_id: chatId }),
  askStream,
  askAgain: (id: number) => request<AskResponse>('POST', `/api/questions/${id}/again`, {}),
  edit: (id: number, question: string) => request<EditResponse>('POST', `/api/questions/${id}/edit`, { question }),
  question: (id: number) => request<SavedAnswer>('GET', `/api/questions/${id}`),
  rows: (url: string) => request<Rows>('GET', url),
  // a chart the app cannot draw itself (a sankey, a gauge ...), made by the AI from the rows - uses AI tokens
  aiChart: (id: number, kind: string) => request<AiChartReply>('POST', `/api/questions/${id}/chart`, { kind }),
  // the other pages
  history: (page: number) => request<HistoryPage>('GET', `/api/history${query({ page: page > 1 ? page : undefined })}`),
  documents: (params: { source?: string; find?: string; q?: string }) =>
    request<DocumentsData>('GET', `/api/documents${query(params)}`),
  data: () => request<DataTables>('GET', '/api/data'),
  audit: (params: Partial<AuditFilters> & { page?: number }) =>
    request<AuditData>('GET', `/api/audit${query(params)}`),
  // the user's own memories
  memories: () => request<MemoryList>('GET', '/api/memories'),
  addMemory: (text: string) => request<MemoryReply>('POST', '/api/memories', { text }),
  deleteMemory: (id: number) => request<{ deleted: number; message: string }>('POST', `/api/memories/${id}/delete`, {}),
  deleteAllMemories: () => request<{ deleted: number; message: string }>('POST', '/api/memories/delete-all', {}),
  // the Knowledge graph (read-only, no AI call)
  // page: the next hits of the same search ("Show more": offset = the hits shown already, limit 1..10, at most 50)
  graphSearch: (q: string, types = '', page: { offset?: number; limit?: number } = {}) =>
    request<GraphSearchReply>('GET', `/api/graph/search${query({ q, types, offset: page.offset, limit: page.limit })}`),
  graphNode: (type: string, id: string, fy: string, limit?: number) =>
    request<GraphNodeReply>('GET', `/api/graph/node${query({ type, id, fy, limit })}`),
  graphSimilar: (customerId: string, fy: string, limit?: number) =>
    request<GraphSimilarReply>('GET', `/api/graph/similar${query({ customer_id: customerId, fy, limit })}`),
  people: () => request<PeopleList>('GET', '/api/users'),
  addPerson: (fields: Record<string, string | boolean>) => request<PersonReply>('POST', '/api/users', fields),
  changePerson: (id: number, fields: Record<string, string | boolean>) =>
    request<PersonReply>('POST', `/api/users/${id}`, fields),
  setActive: (id: number, active: boolean) => request<PersonReply>('POST', `/api/users/${id}/active`, { active }),
  setPassword: (id: number, password1: string, password2: string) =>
    request<PersonReply>('POST', `/api/users/${id}/password`, { password1, password2 }),
}

/** A friendly text for any failure of an API call. */
export function problemText(error: unknown, fallback = 'Something went wrong - please try again.'): string {
  return error instanceof ApiError && error.message ? error.message : fallback
}
