// The welcome banner at the top of Home: the greeting (with a wave), a short line, the India-time clock (the same
// text the top bar of the other pages shows, changing every minute - Home has no top bar), the NOP sales month we
// are in and the FY, and a quick start with example questions (a click opens the Ask page with the question in
// its box - nothing is asked until Ask is pressed).
// It moves a little, calmly: a soft light sweeps slowly over the blue to deep navy background, a few soft shapes
// drift, the text fades in line by line the first time it shows and the hand waves once. None of that when the
// person asked for less motion (the class "mi-hero-motion" is then never set; HomeHero.css also checks it, and
// app.css stops every animation then too). On a wide banner a small machine drawing (HeroFactory.tsx: gears and a
// working pump) sits on the right under the clock; the banner is a container, so the drawing hides where it is narrow.
// The banner is the same deep blue in light and dark mode (it is dark already, the text on it is always white);
// in dark mode a thin light border sets it off from the dark page.
import { ArrowRight, Clock3 } from 'lucide-react'
import type { CSSProperties } from 'react'
import { useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import { wantsMotion } from '../charts/chartOption'
import { Link } from '../router'
import type { HomeCalendar } from '../types'
import HeroFactory from './HeroFactory'
import { istText, useMinute } from './Shell'
import './HomeHero.css'

/** "Good morning / afternoon / evening" by the time on this computer. */
export function greeting(hour: number): string {
  if (hour < 12) return 'Good morning'
  if (hour < 17) return 'Good afternoon'
  return 'Good evening'
}

/** The place of a part in the fade-in (each one starts 60 ms after the one before). */
function step(i: number): CSSProperties {
  return { '--i': i } as CSSProperties
}

export default function HomeHero({ name, calendar, loading, examples }:
  { name: string; calendar: HomeCalendar | null | undefined; loading: boolean; examples: string[] }) {
  const now = useMinute()
  const [motion] = useState(wantsMotion) // decided once, when the banner first shows
  const onDark = 'border-white/20 bg-white/10 text-white'
  return (
    <section aria-label="Welcome" data-motion={motion ? 'on' : 'off'}
      className={cn('mi-hero @container relative overflow-hidden rounded-2xl bg-[linear-gradient(118deg,#0B5FB3_0%,#0A3F7A_38%,#0A2540_70%,#081626_100%)] text-white shadow-[0_22px_44px_-30px_rgba(8,22,38,.85)] dark:border dark:border-white/10 dark:shadow-none',
        motion && 'mi-hero-motion')}>
      {/* the pattern: a soft grid of dots fading in towards the right, the slow light, a blue glow in the corner and
          two soft shapes (all only for the eye, behind the text) */}
      <div aria-hidden="true"
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(rgba(255,255,255,.55)_1px,transparent_1.2px)] bg-size-[18px_18px] opacity-25 [mask-image:linear-gradient(100deg,transparent_25%,#000_85%)]" />
      <div aria-hidden="true" className="mi-hero-sheen" />
      <div aria-hidden="true" className="mi-hero-orb mi-hero-orb-glow" />
      <div aria-hidden="true" className="mi-hero-orb mi-hero-orb-soft" />
      <div aria-hidden="true" className="mi-hero-orb mi-hero-orb-ring" />

      <div className="relative flex flex-wrap items-start justify-between gap-x-8 gap-y-4 px-7 pt-6 pb-5 max-[760px]:px-4.5 max-[760px]:pt-5">
        <HeroFactory motion={motion} />
        <div className="flex min-w-0 flex-col gap-2.5">
          <h2 className="mi-hero-in m-0 text-[27px] leading-tight font-semibold text-white max-[760px]:text-[22px]" style={step(0)}>
            {greeting(now.getHours())}, {name} <span aria-hidden="true" className="mi-hero-wave">👋</span>
          </h2>
          <p className="mi-hero-in text-[13.5px] leading-relaxed text-white/80" style={step(1)}>
            Ask the company data a question in plain English - here is where things stand today.
          </p>
          {(loading || calendar) && (
            <ul className="mt-0.5 flex flex-wrap gap-1.5" aria-label="Today">
              {loading ? (
                <li><Skeleton className="h-6 w-60 max-w-full rounded-full bg-white/15" /></li>
              ) : calendar ? (
                <>
                  <li className="mi-hero-in" style={step(2)}>
                    <Badge variant="outline" className="h-auto border-white/25 bg-white/15 py-1 whitespace-normal text-white">
                      NOP sales month {calendar.month} · {calendar.month_from} to {calendar.month_to}
                    </Badge>
                  </li>
                  <li className="mi-hero-in" style={step(3)}><Badge variant="outline" className={cn(onDark, 'py-1')}>{calendar.fy_label}</Badge></li>
                </>
              ) : null}
            </ul>
          )}
        </div>
        {/* the clock: the date and time in India, on a soft see-through pill (above the greeting on a phone) */}
        <p data-slot="hero-clock"
          className="mi-hero-in flex items-center gap-1.5 rounded-full border border-white/20 bg-white/10 px-3.5 py-1.5 text-[12.5px] font-medium whitespace-nowrap text-white tabular-nums shadow-[inset_0_1px_0_rgba(255,255,255,.12)] backdrop-blur-sm max-[760px]:order-first max-[760px]:whitespace-normal"
          style={step(1)}>
          <Clock3 aria-hidden="true" className="size-3.5 flex-none opacity-85" />
          <time dateTime={now.toISOString()}>{istText(now)}</time>
        </p>
      </div>

      {/* quick start: the Ask page opens with the question in its box - nothing is sent until Ask is pressed */}
      {examples.length > 0 && (
        <div className="mi-hero-in relative flex flex-wrap items-center gap-x-2.5 gap-y-2 border-t border-white/10 bg-black/20 px-7 py-3 max-[760px]:px-4.5"
          style={step(4)}>
          <span className="text-[11px] font-semibold tracking-[.06em] text-white/70 uppercase" id="home-try">Try a question</span>
          <ul className="flex min-w-0 flex-wrap gap-2" aria-labelledby="home-try">
            {examples.map((example) => (
              <li key={example} className="min-w-0 max-w-full">
                <Link to={`/new?q=${encodeURIComponent(example)}`}
                  className="flex max-w-full items-center gap-1.5 rounded-full border border-white/20 bg-white/10 px-3 py-1 text-[12.5px] text-white! transition-colors outline-none hover:border-white/45 hover:bg-white/20 hover:text-white! focus-visible:ring-3 focus-visible:ring-white/50">
                  <span className="min-w-0 [overflow-wrap:anywhere]">{example}</span>
                  <ArrowRight aria-hidden="true" className="size-3.5 flex-none opacity-80" />
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
