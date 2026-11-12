// Home: the two big feature cards right under the welcome banner - Assistant (the blue brand) and the Knowledge graph
// (teal, so the two differ). Both work in light and dark (tokens and light / dark pairs; HomeFeatures.css has the
// pictures' own dark colours). Each card says what the page does in one or two lines, shows three small points with icons and
// has one big button that opens the page (the card itself is not a link). On the right a small moving picture:
// a chat bubble "typing" and then a tiny bar chart growing (Assistant), dots joined by lines that draw themselves
// and gently pulse (the graph). The pictures are only decoration (aria-hidden), their motion is in
// HomeFeatures.css and stops when the person asked for less motion.
// Each card measures its own width (a container query): the picture shows only where the card is wide enough,
// so on a phone the text and the button get the whole card. The two cards stand side by side once the room
// they have is wide enough for both pictures, else one under the other.
import { ArrowRight, BarChart3, Box, FileSpreadsheet, type LucideIcon, MessageSquare, Network, Search } from 'lucide-react'
import type { ReactNode } from 'react'
import { buttonVariants } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { Link } from '../router'
import './HomeFeatures.css'

interface Feature {
  key: 'ask' | 'graph'
  title: string
  text: string
  points: [LucideIcon, string][]
  to: string
  button: string
  icon: LucideIcon
  picture: ReactNode
  // the colours of the card: the soft glow in the corner, the icon circle, the points' icons, the button
  look: { glow: string; icon: string; point: string; button: string }
}

/** Assistant: a chat bubble with three dots typing, then a small bar chart growing under it. */
function AskPicture() {
  return (
    <div className="hf-ask" aria-hidden="true">
      <div className="hf-bubble"><span /><span /><span /></div>
      <div className="hf-bars"><span /><span /><span /><span /></div>
    </div>
  )
}

// the dots of the graph picture (x, y, radius) and the lines between them (by dot number)
const DOTS: [number, number, number][] = [[75, 62, 9], [28, 30, 6], [124, 26, 6], [22, 100, 5.5], [122, 104, 6.5], [76, 14, 4.5]]
const LINES: [number, number][] = [[0, 1], [0, 2], [0, 3], [0, 4], [1, 5], [5, 2], [3, 4]]

/** The Knowledge graph: dots joined by lines that draw themselves, the dots pulsing gently. */
function GraphPicture() {
  return (
    <svg className="hf-graph" viewBox="0 0 150 124" aria-hidden="true" focusable="false">
      {LINES.map(([a, b], i) => (
        <line key={`${a}-${b}`} className="hf-line" pathLength={1} style={{ animationDelay: `${i * 0.25}s` }}
          x1={DOTS[a][0]} y1={DOTS[a][1]} x2={DOTS[b][0]} y2={DOTS[b][1]} />
      ))}
      {DOTS.map(([x, y, r], i) => (
        <circle key={`${x}-${y}`} className={i === 0 ? 'hf-dot hf-dot-main' : 'hf-dot'} style={{ animationDelay: `${i * 0.35}s` }}
          cx={x} cy={y} r={r} />
      ))}
    </svg>
  )
}

const FEATURES: Feature[] = [
  {
    key: 'ask',
    title: 'Assistant',
    text: 'Ask the company data in plain English. You get the answer in words, a chart and an Excel file - and every number comes from the database.',
    points: [[MessageSquare, 'Plain English'], [BarChart3, 'Charts'], [FileSpreadsheet, 'Excel']],
    to: '/ask',
    button: 'Open the Assistant',
    icon: MessageSquare,
    picture: <AskPicture />,
    look: {
      glow: 'bg-[radial-gradient(closest-side,rgba(11,95,179,.16),transparent)] dark:bg-[radial-gradient(closest-side,rgba(76,154,255,.18),transparent)]',
      icon: 'bg-primary-soft text-primary',
      point: 'text-primary',
      button: 'bg-primary text-primary-foreground! shadow-[0_8px_18px_-12px_rgba(11,95,179,.75)] hover:bg-primary/90 hover:text-primary-foreground! focus-visible:ring-primary/40',
    },
  },
  {
    key: 'graph',
    title: 'Knowledge graph',
    text: 'See how customers, products, sales people and states are linked. Go into any dot, compare similar customers - in 2D or 3D.',
    points: [[Network, 'Links'], [Search, 'Search any name'], [Box, '2D / 3D']],
    to: '/graph',
    button: 'Open Knowledge graph',
    icon: Network,
    picture: <GraphPicture />,
    look: {
      glow: 'bg-[radial-gradient(closest-side,rgba(13,148,136,.18),transparent)] dark:bg-[radial-gradient(closest-side,rgba(45,212,191,.16),transparent)]',
      icon: 'bg-teal-500/12 text-teal-700 dark:bg-teal-400/15 dark:text-teal-300',
      point: 'text-teal-700 dark:text-teal-300',
      button: 'bg-teal-700 text-white! shadow-[0_8px_18px_-12px_rgba(15,118,110,.75)] hover:bg-teal-800 hover:text-white! focus-visible:ring-teal-600/45 dark:bg-teal-600 dark:hover:bg-teal-500',
    },
  },
]

function FeatureCard({ feature }: { feature: Feature }) {
  const { title, text, points, to, button, icon: Icon, picture, look } = feature
  return (
    <Card data-feature={feature.key}
      className="@container relative overflow-hidden transition-[translate,box-shadow] duration-200 ease-out hover:-translate-y-1 hover:shadow-[0_22px_40px_-26px_rgba(17,16,16,.45)] motion-reduce:hover:translate-y-0">
      {/* a soft colour glow in the top right corner */}
      <div aria-hidden="true" className={cn('pointer-events-none absolute -top-24 -right-16 size-64 rounded-full', look.glow)} />

      <div className="relative grid h-full gap-4 px-6 py-5 max-[760px]:px-4.5 @min-[420px]:grid-cols-[minmax(0,1fr)_132px] @min-[420px]:items-center">
        <div className="flex min-w-0 flex-col items-start gap-3">
          <div className="flex items-center gap-2.5">
            <span className={cn('grid size-10 flex-none place-items-center rounded-xl', look.icon)}>
              <Icon aria-hidden="true" className="size-5" />
            </span>
            <h2 className="m-0 text-[19px] leading-tight font-semibold text-heading">{title}</h2>
          </div>
          <p className="m-0 text-[13.5px] leading-relaxed text-muted-foreground">{text}</p>
          <ul className="flex flex-wrap gap-x-4 gap-y-1.5" aria-label={`${title}: what you get`}>
            {points.map(([PointIcon, label]) => (
              <li key={label} className="flex items-center gap-1.5 text-[13px] font-medium text-heading">
                <PointIcon aria-hidden="true" className={cn('size-4 flex-none', look.point)} />{label}
              </li>
            ))}
          </ul>
          <Link to={to}
            className={cn(buttonVariants({ size: 'lg' }), 'mt-1 h-11 px-5 text-[15px] font-semibold', look.button)}>
            {button}<ArrowRight aria-hidden="true" className="size-[18px]" />
          </Link>
        </div>
        <div className="hidden justify-center @min-[420px]:flex">{picture}</div>
      </div>
    </Card>
  )
}

export default function HomeFeatures() {
  return (
    <section aria-label="The Assistant and the Knowledge graph" className="@container min-w-0">
      <div className="grid gap-4 @min-[900px]:grid-cols-2">
        {FEATURES.map((feature) => <FeatureCard key={feature.key} feature={feature} />)}
      </div>
    </section>
  )
}
