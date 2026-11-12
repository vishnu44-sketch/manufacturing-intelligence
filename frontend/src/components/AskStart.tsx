// The start screen of the Ask page (a new / empty chat): in the middle of the page a big heading, one grey
// line, the question box (AskPage passes it in as children, so the box stays AskPage's own) and under it
// four starter cards - Sales, Customers, Open orders, Stock. A click on a card puts a fitting question in
// the box (the user's own example questions where they fit, else a fixed one); the user presses send.
// Drawn with Tailwind token classes only, so it follows the light and the dark theme.
import type { ReactNode } from 'react'
import { Boxes, ClipboardList, TrendingUp, Users, type LucideIcon } from 'lucide-react'
import { cn } from '@/lib/utils'

interface Starter {
  title: string
  icon: LucideIcon
  fits: RegExp // an example question with these words is used for this card
  question: string // else this one
}

// in the order they show; the examples are handed out most exact first (see starterQuestions)
const STARTERS: Starter[] = [
  { title: 'Sales', icon: TrendingUp, fits: /\b(sales|invoice|revenue)/i,
    question: 'Net sales of the last 6 NOP months as a line chart' },
  { title: 'Customers', icon: Users, fits: /\bcustomer/i,
    question: 'Top 10 customers this FY by net sales' },
  { title: 'Open orders', icon: ClipboardList, fits: /\bopen\b.*\borders?\b|\borders?\b.*\bopen\b/i,
    question: 'List the open sales orders up to today' },
  { title: 'Stock', icon: Boxes, fits: /\b(stock|inventory)/i,
    question: 'Stock value by item group on the latest stock report' },
]

/** The question behind each starter card: one of the user's example questions when it fits the card (each
 *  example is used once; "Open orders", "Stock" and "Customers" choose before the wide "Sales"), else the fixed one. */
export function starterQuestions(examples: string[]): string[] {
  const left = [...examples]
  const picked: string[] = STARTERS.map((starter) => starter.question)
  for (const i of [2, 3, 1, 0]) {
    const at = left.findIndex((example) => STARTERS[i].fits.test(example))
    if (at >= 0) picked[i] = left.splice(at, 1)[0]
  }
  return picked
}

export default function AskStart({ examples, onPick, children }:
  { examples: string[]; onPick: (question: string) => void; children: ReactNode }) {
  const questions = starterQuestions(examples)
  return (
    <div id="welcome" className="mx-auto my-auto flex w-full max-w-[760px] flex-col items-center px-1 pt-10 pb-6 max-[700px]:pt-4">
      <h2 className="text-center text-[32px] leading-tight font-bold tracking-tight text-heading max-[700px]:text-2xl">
        What would you like to know?
      </h2>
      <p className="mt-2.5 max-w-[560px] text-center text-sm leading-relaxed text-muted-foreground">
        Ask about sales, customers, orders, stock and the company documents - in plain English.
      </p>

      <div className="mt-7 w-full max-[700px]:mt-5">{children}</div>

      <ul aria-label="Starter questions" className="mt-4 grid w-full grid-cols-2 gap-3 max-[600px]:grid-cols-1">
        {STARTERS.map((starter, i) => (
          <li key={starter.title}>
            <button type="button" title={questions[i]} onClick={() => onPick(questions[i])}
                    className={cn('group/start flex h-full w-full items-center gap-3 rounded-xl border border-border bg-card px-3.5 py-3 text-left shadow-xs',
                      'transition-[border-color,box-shadow] hover:border-primary/50 hover:shadow-md',
                      'focus-visible:border-primary focus-visible:ring-3 focus-visible:ring-primary/20 focus-visible:outline-none')}>
              <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-primary-soft text-primary" aria-hidden="true">
                <starter.icon className="size-[18px]" strokeWidth={2} />
              </span>
              <span className="flex min-w-0 flex-col gap-0.5">
                <span className="text-sm font-semibold text-heading group-hover/start:text-primary">{starter.title}</span>
                <span className="truncate text-xs text-muted-foreground">{questions[i]}</span>
              </span>
            </button>
          </li>
        ))}
      </ul>

      <div className="mt-5 text-center text-[11px] leading-normal text-faint">
        Enter to send · Shift+Enter for a new line · A month name means the NOP sales month (21st to 20th) unless you
        say "calendar month".
      </div>
    </div>
  )
}
