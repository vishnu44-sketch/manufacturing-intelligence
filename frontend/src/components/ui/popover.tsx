// shadcn/ui Popover. portal={false} keeps the content in its place in the page (the chat list's "..."
// menu stays inside its chat row); it still floats above the page.
import * as PopoverPrimitive from '@radix-ui/react-popover'
import type { ComponentProps } from 'react'
import { cn } from '@/lib/utils'

function Popover(props: ComponentProps<typeof PopoverPrimitive.Root>) {
  return <PopoverPrimitive.Root data-slot="popover" {...props} />
}

function PopoverTrigger(props: ComponentProps<typeof PopoverPrimitive.Trigger>) {
  return <PopoverPrimitive.Trigger data-slot="popover-trigger" {...props} />
}

function PopoverContent({ className, align = 'center', sideOffset = 4, portal = true, ...props }:
  ComponentProps<typeof PopoverPrimitive.Content> & { portal?: boolean }) {
  const content = (
    <PopoverPrimitive.Content data-slot="popover-content" align={align} sideOffset={sideOffset}
      className={cn(
        'z-50 w-72 origin-(--radix-popover-content-transform-origin) rounded-xl border border-border bg-popover p-3 text-popover-foreground shadow-[0_16px_36px_-18px_color-mix(in_srgb,var(--shadow-c)_45%,transparent)] outline-none',
        'data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95',
        'data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2',
        className)}
      {...props} />
  )
  return portal ? <PopoverPrimitive.Portal>{content}</PopoverPrimitive.Portal> : content
}

export { Popover, PopoverContent, PopoverTrigger }
