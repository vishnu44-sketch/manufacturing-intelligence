// The shapes the Django JSON API (portal/api.py) sends.

export interface Me {
  username: string
  name: string
  is_staff: boolean
  examples: string[]
  max_question_chars: number
}

export interface ChatSummary {
  id: number
  title: string
  archived: boolean
  created_at: string
  created_text: string // '03 Nov 2026 10:15 AM' (India time)
  updated_at: string
  updated_text: string // '03 Nov, 10:15 AM' (the chat menu: "last one ...")
  group?: string // Today / Yesterday / Previous 7 days / Older (only in the list)
  questions?: number // only in the list
}

export interface TimeStep {
  label: string
  secs: number
  note: string
}

export interface Source {
  kind: string // table / rule / example / pdf
  heading: string
}

export type Status = 'ok' | 'docs' | 'nodata' | 'refused' | 'error' | 'memory'

// one saved question as the answer card shows it
export interface Card {
  id: number
  text: string
  status: Status
  answer: string
  understood_as: string
  backup_model: string // '' = the main model answered
  token_notice: string // only right after asking
  time_steps: TimeStep[]
  sql: string // '' when the card has no rows (docs, nodata, refused, error, memory)
  sources: Source[]
  secs: number
  tries: number
  row_count: number | null
  has_rows: boolean
  rows_url: string
  excel_url: string
  created_at: string
  created_text: string
  edited: boolean
}

export interface ChatDetail {
  chat: ChatSummary
  total: number
  earlier: number // older questions of the chat that are not sent (they are in History)
  cards: Card[]
}

export interface Header {
  name: string
  num: boolean
}

export interface Cell {
  text: string
  num: boolean
}

export interface Rows {
  headers: Header[]
  rows: Cell[][]
  row_count: number
  truncated: boolean
  rows_error: string
}

/** POST /api/questions/<id>/chart: a chart the AI made from the rows, as an ECharts option (plain JSON, checked
 *  by the server). recorded = its tokens were added to the question's own token count. */
export interface AiChartReply {
  option: Record<string, unknown>
  tokens: number | null
  model: string
  recorded: boolean
}

export interface AskResponse {
  chat: ChatSummary
  card: Card
}

/** One line of /api/ask/stream: a step starts, a piece of the answer, the finished card, or a failure. */
export type StreamEvent =
  | { type: 'step'; label: string }
  | { type: 'token'; text: string }
  | { type: 'done'; chat: ChatSummary; card: Card }
  | { type: 'error'; message: string }

export interface ChatList {
  chats: ChatSummary[]
  removed: ChatSummary[] // removed (archived) chats, newest first
}

export interface EditResponse {
  chat: ChatSummary | null
  card: Card
  replaced: number // the id of the card the new one replaces
}

export interface SavedAnswer {
  card: Card
  chat: ChatSummary | null // its chat when it is the user's own
}

export interface UsageRow {
  model: string
  tokens: string // '18,240'
  limit: string
  pct: number
  questions_left: number
  rolling: string // Groq's real count, the last 24 hours
  week_tokens: string
  week_questions: number
}

export interface Usage {
  rows: UsageRow[]
  period_start: string // 'Thu 08-Oct 10:05 AM'; '' = no daily period is running
  period_end: string
  week_start: string
  week_end: string
}

export interface HistoryLine {
  id: number
  created_text: string
  text: string
  understood_as: string
  edited: boolean // replaced by a newer version
  answer: string // cut at 140 characters
  rows_count: number | null
  secs_text: string
  tokens_text: string
  status: Status
  model: string
  backup: boolean
  ask_again: string
  excel_url: string
}

export interface HistoryPage {
  questions: HistoryLine[]
  page: number
  pages: number
  count: number
  has_previous: boolean
  has_next: boolean
  usage: Usage
}

export interface Piece {
  no: number
  id: string
  source: string
  kind: string
  heading: string
  text: string
}

export interface Hit {
  kind: string
  score: number | null
  heading: string
  source: string
  text: string
}

export interface DocumentsData {
  total: number
  counts: { source: string; count: number }[]
  pieces: Piece[]
  hits: Hit[]
  tables: { all: boolean; names: string[] } | null
  search_error: string
  store_empty: string
  store_error: string
  vector_db: string
  source: string
  find: string
  question: string
}

export interface TableCount {
  name: string
  note: string
  kind: string // Main data / Lookup / Load history / Other
  rows: number
  rows_text: string
}

export interface DataTables {
  database: string
  mysql_error: string
  tables: TableCount[]
  table_count: number
  total: string
  invoices_from: string
  invoices_to: string
  last_load: string
}

export interface Person {
  id: number
  username: string
  name: string
  first_name: string
  last_name: string
  email: string
  is_staff: boolean
  is_superuser: boolean
  is_active: boolean
  last_login: string // '' = never
  is_me: boolean
}

export interface PeopleList {
  people: Person[]
  can_add: boolean
  can_change: boolean
  can_set_roles: boolean
  admin_url: string
}

export interface PersonReply {
  person: Person
  message: string
}

// one fact the user asked the app to remember (used in all his later chats)
export interface Memory {
  id: number
  text: string
  question_id: number | null // the question that said "Remember ..." (null = added on the Memory page)
  created_at: string
  created_text: string // '03 Nov 2026 10:15 AM' (India time)
}

export interface MemoryList {
  memories: Memory[] // newest first
  limit: number // at most this many per user
  max_chars: number
}

export interface MemoryReply {
  memory: Memory
  message: string
}

// one line of the audit log (staff): who did what and when
export interface AuditLine {
  id: number
  created_at: string
  created_text: string // '03 Nov 2026 10:15:07 AM' (India time)
  username: string // '' = no user (an MCP call)
  user_id: number | null // null = no user, or the person was deleted later
  action: string // the code, e.g. chat_deleted
  action_text: string // in plain words, e.g. Chat deleted
  target: string // e.g. 'chat 12', 'user 5', 'memory 3'
  details: Record<string, unknown> // never a password
  summary: string // the details in one short line
  questions: number[] // the saved answers it is about (staff open them, also of a deleted chat)
  ip: string
  user_agent: string
}

export interface AuditFilters {
  user: string
  action: string
  from: string // YYYY-MM-DD
  to: string
  q: string
}

export interface AuditData {
  lines: AuditLine[] // newest first, 50 per page
  page: number
  pages: number
  count: number
  has_previous: boolean
  has_next: boolean
  actions: { code: string; text: string }[]
  filters: AuditFilters
}

// ------------------------------------------------------------------ the Knowledge graph (/api/graph/...)
export type GraphNodeType = 'customer' | 'product' | 'category' | 'sales_person' | 'state' | 'sale_type' | 'document'

export interface GraphNode {
  id: string // 'customer:16' - the same on every call
  type: GraphNodeType
  type_name: string // 'Customer', 'State / country' ...
  key: string // '16', 'Trochoid pumps'
  label: string
  sub: string // a short second line: the place, the product code ...
  amount: number | null // net sales in the period (null: none, e.g. a document page)
  amount_text: string // the same with Indian commas
  quantity?: number
  quantity_text?: string
  invoices?: number
  invoices_text?: string
  lines?: number
  data_from?: string
  data_to?: string
  ask?: string // a question for the Ask page about this node
  text?: string // a document page: its first words
  // a similar customer
  shared_products?: number
  products?: number
  score?: number
  score_text?: string
  shared_amount_text?: string
  // a search hit
  fuzzy?: boolean // a close spelling of what was typed ("Did you mean ...?")
}

export interface GraphEdge {
  id: string
  source: string
  target: string
  type: string // BOUGHT, IN_CATEGORY, HANDLED_BY, IN_STATE, BUYS_AS, COVERED_BY, BUYS_LIKE
  amount?: number
  amount_text?: string
  quantity?: number
  quantity_text?: string
  invoices?: number
  invoices_text?: string
  mentions?: number // COVERED_BY: how often the page names the category / series
  model?: string // COVERED_BY: the model code the page lists
  through?: string // COVERED_BY of a product: through its category
  shared_products?: number // BUYS_LIKE
  score_text?: string
}

export interface GraphPeriod {
  fy: string // '' = all data
  label: string // 'FY 2026-27 so far'
  from: string
  to: string
  so_far: boolean
  text: string // 'FY 2026-27 so far (01-Apr-2026 to 04-Nov-2026)'
}

export interface GraphGroup {
  edge: string
  type: GraphNodeType
  shown: number
  total: number
}

export interface GraphNodeReply {
  node: GraphNode
  period: GraphPeriod
  neighbours: GraphNode[]
  edges: GraphEdge[]
  groups: GraphGroup[]
  notes: string[]
}

export interface GraphSearchReply {
  q: string
  results: GraphNode[]
  match?: 'name' | 'top' | 'type' // name holds the text / a type word ("customers") / a type word and text
  match_type?: GraphNodeType | ''
  note?: string // a line for under the search box ('Top 10 customers by net sales ...')
  fuzzy?: boolean // some hits are close spellings
  total?: number // how many nodes the search finds in all (none for close spellings: no "Show more")
}

export interface GraphSimilarReply {
  customer: GraphNode
  period: GraphPeriod
  products: number // how many products this customer bought
  similar: GraphNode[]
  edges: GraphEdge[]
}

// the Home page (/api/home): every part comes with its own error text ('' = fine)
export interface HomeChange {
  pct: number
  direction: 'up' | 'down' | 'flat'
  text: string // '20.0% vs Sep 2026'
}

export interface HomeKpi {
  key: string // month_sales, fy_sales, customers, products, open_orders, stock, top_customer, top_product
  label: string
  name?: string // top_customer / top_product: the customer's or product's name ('' when nothing was sold)
  money: boolean // an amount in INR (value is the number, text the full amount as the Ask page writes it)
  value: number
  text: string // 'INR 1,200,000.00' / '2,063'
  note: string // the dates or what it counts
  change: HomeChange | null // against the previous period, where that makes sense
  trend?: HomeTrendPoint[] | null // up to 6 NOP sales months, oldest first (null / missing: no small line)
  ask?: string // a question about this number for the Ask page (missing on an older server)
  facts?: string[] | null // 1-3 short facts shown as chips where there is no small line ('10 orders', '14 lines')
}

export interface HomeTrendPoint {
  label: string // 'May 2026'
  value: number
}

/** One of the user's own last questions on Home (opens its saved answer, no AI call). */
export interface HomeRecent {
  id: number
  text: string
  status: Status | string
  when: string // '05-Nov 2:04 PM'
  url: string // '/q/<id>'
}

export interface HomeCalendar {
  today: string // '05-Nov-2026'
  month: string // the NOP sales month we are in: 'Nov 2026'
  month_from: string // '21-Oct-2026'
  month_to: string // '20-Nov-2026'
  fy: string
  fy_label: string // 'FY 2026-27'
}

export interface HomeTable {
  table: string // fact_invoice_lines
  name: string // 'Sales invoices'
  note: string
  rows: number
  rows_text: string
  from: string // '' for a table without dates
  to: string
  after_today: boolean // the data also has test rows dated after today
}

export interface HomeConnection {
  key: string // ai_gold, app_db, docs, pdfs, groq
  name: string // 'MySQL ai_gold' - names only, never a host, a port or a key
  what: string
  ok: boolean
  note: string // 'Reachable', '91 pieces', 'Key set' ...
}

export interface HomeUsage {
  questions_today: number // this user's own questions today
  my_tokens_today: number
  my_tokens_text: string
  model: string
  tokens_24h: string // the whole app, the last 24 hours: what Groq's daily limit counts
  limit: string
  pct: number
  period_tokens: string // the app's daily period (as on History)
  period_pct: number
  questions_left: number
  period_end: string // '' when no period is running
}

export interface HomeData {
  first_name: string
  today: string
  calendar: HomeCalendar | null
  kpis: HomeKpi[]
  kpi_error: string
  tables: HomeTable[]
  tables_error: string
  connections: HomeConnection[]
  connections_error: string
  usage: HomeUsage | null
  usage_error: string
  model: string
  recent?: HomeRecent[] // the user's last 5 questions, newest first (missing on an older server)
  recent_error?: string
}
