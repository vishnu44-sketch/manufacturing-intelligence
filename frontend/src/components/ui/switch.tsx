// A shadcn/ui-style Switch (on / off), made from a plain button with role="switch" (no Radix package is
// needed for it). Brand colour when on; follows the light / dark look through the colour tokens.
import type { ComponentProps } from 'react'
import { cn } from '@/lib/utils'

function Switch({ checked, onCheckedChange, className, ...props }:
  Omit<ComponentProps<'button'>, 'onChange'> & { checked: boolean; onCheckedChange: (checked: boolean) => void }) {
  return (
    <button type="button" role="switch" aria-checked={checked} data-state={checked ? 'checked' : 'unchecked'}
      onClick={() => onCheckedChange(!checked)}
      className={cn(
        'inline-flex h-5 w-9 flex-none cursor-pointer items-center rounded-full p-0.5 transition-colors outline-none',
        'focus-visible:ring-3 focus-visible:ring-ring/40 disabled:cursor-not-allowed disabled:opacity-50',
        checked ? 'bg-primary' : 'bg-input',
        className)}
      {...props}>
      <span aria-hidden="true"
        className={cn('block size-4 rounded-full bg-card shadow-xs transition-transform', checked && 'translate-x-4')} />
    </button>
  )
}

export { Switch }
