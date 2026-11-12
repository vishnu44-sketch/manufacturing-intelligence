// A row of toggle buttons drawn like shadcn/ui's Tabs list (Chart | Table, Line | Bar | Donut). They stay
// real buttons with aria-pressed (not tabs), so screen readers and the tests use them as before.
import type { ComponentProps } from 'react'
import { cn } from '@/lib/utils'

function Segmented({ className, ...props }: ComponentProps<'span'>) {
  return (
    <span role="group" data-slot="segmented"
      className={cn('inline-flex h-8 items-center gap-0.5 rounded-lg bg-secondary p-0.5 text-muted-foreground', className)}
      {...props} />
  )
}

function SegmentedItem({ pressed, className, ...props }: ComponentProps<'button'> & { pressed: boolean }) {
  return (
    <button type="button" aria-pressed={pressed} data-state={pressed ? 'on' : 'off'}
      className={cn(
        'inline-flex h-7 items-center justify-center gap-1.5 rounded-md px-3 text-xs font-medium whitespace-nowrap transition-all outline-none',
        'hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/40 [&_svg]:size-3.5 [&_svg]:shrink-0',
        'data-[state=on]:cursor-default data-[state=on]:bg-card data-[state=on]:text-primary data-[state=on]:shadow-sm',
        className)}
      {...props} />
  )
}

export { Segmented, SegmentedItem }
