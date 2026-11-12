// shadcn/ui Input. styles/app.css styles every input[type=text] (and every input:focus) on its own,
// outside any cascade layer, so it would beat these classes: the properties it sets are marked
// important (!) here.
import type { ComponentProps } from 'react'
import { cn } from '@/lib/utils'

function Input({ className, ...props }: ComponentProps<'input'>) {
  return (
    <input data-slot="input"
      className={cn(
        'h-8 w-full min-w-0 rounded-md! border! border-input! bg-card! px-2.5! py-1! text-[13px]! text-foreground! shadow-xs outline-none transition-[color,box-shadow]',
        'placeholder:text-muted-foreground focus-visible:border-primary! focus-visible:ring-3 focus-visible:ring-primary/15 disabled:cursor-not-allowed disabled:opacity-50',
        className)}
      {...props} />
  )
}

export { Input }
