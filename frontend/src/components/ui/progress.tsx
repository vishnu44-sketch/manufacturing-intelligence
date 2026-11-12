// shadcn/ui Progress, as a plain div (no Radix): a grey track with a coloured bar of value% (0-100).
// role="progressbar" with aria-valuenow / min / max; indicatorClassName colours the bar.
import type { ComponentProps } from 'react'
import { cn } from '@/lib/utils'

function Progress({ className, indicatorClassName, value = 0, ...props }:
  ComponentProps<'div'> & { value?: number; indicatorClassName?: string }) {
  const width = Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0))
  return (
    <div data-slot="progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(width)}
      className={cn('relative h-2 w-full overflow-hidden rounded-full bg-secondary', className)} {...props}>
      <div data-slot="progress-indicator" className={cn('h-full rounded-full bg-primary transition-[width] duration-500', indicatorClassName)}
        style={{ width: `${width}%` }} />
    </div>
  )
}

export { Progress }
