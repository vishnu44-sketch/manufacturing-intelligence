// A small turning circle for a busy button (shadcn/ui's Spinner, without its own role: the button or the
// text next to it says what is happening).
import { LoaderCircle } from 'lucide-react'
import { cn } from '@/lib/utils'

function Spinner({ className }: { className?: string }) {
  return <LoaderCircle aria-hidden="true" className={cn('size-3.5 animate-spin', className)} />
}

export { Spinner }
