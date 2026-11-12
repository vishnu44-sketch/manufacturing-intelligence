// shadcn/ui Card (only the parts the Ask page uses).
import type { ComponentProps } from 'react'
import { cn } from '@/lib/utils'

function Card({ className, ...props }: ComponentProps<'div'>) {
  return (
    <div data-slot="card"
      className={cn('min-w-0 rounded-xl border border-border bg-card text-card-foreground shadow-[0_10px_26px_-24px_color-mix(in_srgb,var(--shadow-c)_35%,transparent)]', className)}
      {...props} />
  )
}

function CardContent({ className, ...props }: ComponentProps<'div'>) {
  return <div data-slot="card-content" className={cn('px-5 py-4 max-[760px]:px-3.5', className)} {...props} />
}

export { Card, CardContent }
