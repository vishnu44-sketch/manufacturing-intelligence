// shadcn/ui Textarea. styles/app.css styles every textarea (and textarea:focus) on its own, outside any
// cascade layer, so it would beat these classes: the properties it sets are marked important (!) here.
import type { ComponentProps } from 'react'
import { cn } from '@/lib/utils'

function Textarea({ className, ...props }: ComponentProps<'textarea'>) {
  return (
    <textarea data-slot="textarea"
      className={cn(
        'flex min-h-16 w-full rounded-lg! border! border-input! bg-card! px-3! py-2! text-sm! leading-6! text-foreground! resize-none! shadow-xs outline-none transition-[color,box-shadow]',
        'placeholder:text-muted-foreground focus-visible:border-primary! focus-visible:ring-3 focus-visible:ring-primary/15 read-only:text-muted-foreground! disabled:cursor-not-allowed disabled:opacity-50',
        className)}
      {...props} />
  )
}

export { Textarea }
