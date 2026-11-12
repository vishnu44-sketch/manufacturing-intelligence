// shadcn/ui Table: the scroll box, then the table parts. The header row sticks to the top of the box,
// every other row is shaded (zebra).
import type { ComponentProps } from 'react'
import { cn } from '@/lib/utils'

function Table({ className, containerClassName, ...props }: ComponentProps<'table'> & { containerClassName?: string }) {
  return (
    <div data-slot="table-container" className={cn('relative w-full overflow-auto', containerClassName)}>
      <table data-slot="table" className={cn('w-full caption-bottom border-separate border-spacing-0 text-[13px]', className)} {...props} />
    </div>
  )
}

function TableHeader({ className, ...props }: ComponentProps<'thead'>) {
  return <thead data-slot="table-header" className={className} {...props} />
}

function TableBody({ className, ...props }: ComponentProps<'tbody'>) {
  return <tbody data-slot="table-body" className={cn('[&>tr:last-child>td]:border-b-0', className)} {...props} />
}

function TableRow({ className, ...props }: ComponentProps<'tr'>) {
  return <tr data-slot="table-row" className={cn('transition-colors even:bg-muted hover:bg-accent', className)} {...props} />
}

function TableHead({ className, ...props }: ComponentProps<'th'>) {
  return (
    <th data-slot="table-head"
      className={cn('sticky top-0 z-10 h-10 border-b border-border bg-muted px-3.5 text-left align-middle text-[11px] font-semibold tracking-wide whitespace-nowrap text-muted-foreground uppercase', className)}
      {...props} />
  )
}

function TableCell({ className, ...props }: ComponentProps<'td'>) {
  return <td data-slot="table-cell" className={cn('border-b border-border/70 px-3.5 py-2.5 align-middle text-body', className)} {...props} />
}

export { Table, TableBody, TableCell, TableHead, TableHeader, TableRow }
