// shadcn/ui Separator, as a plain div (no Radix): a 1px line across (horizontal) or down (vertical), with
// role="separator". decorative (the default) also hides it from screen readers - a line only for the eye.
import type { ComponentProps } from 'react'
import { cn } from '@/lib/utils'

function Separator({ className, orientation = 'horizontal', decorative = true, ...props }:
  ComponentProps<'div'> & { orientation?: 'horizontal' | 'vertical'; decorative?: boolean }) {
  return (
    <div data-slot="separator" data-orientation={orientation} role="separator" aria-orientation={orientation}
      aria-hidden={decorative || undefined}
      className={cn('shrink-0 bg-border', orientation === 'horizontal' ? 'h-px w-full' : 'h-full w-px', className)}
      {...props} />
  )
}

export { Separator }
