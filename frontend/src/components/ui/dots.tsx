// Three pulsing brand-blue dots ("working on it"), drawn with Tailwind (blink is the keyframes of styles/app.css).
import { cn } from '@/lib/utils'

function Dots({ className }: { className?: string }) {
  return (
    <span aria-hidden="true" className={cn('inline-flex items-center gap-1', className)}>
      {[0, 150, 300].map((delay) => (
        <i key={delay} className="size-1.5 rounded-full bg-ring animate-[blink_1.2s_ease-in-out_infinite_both]"
          style={{ animationDelay: `${delay}ms` }} />
      ))}
    </span>
  )
}

export { Dots }
