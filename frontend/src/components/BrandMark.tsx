// The app's mark: a factory on the blue tile, with a small green "live" dot (the top bar and the sign-in page).
import { Factory } from 'lucide-react'

export default function BrandMark({ size = 36 }: { size?: number }) {
  return (
    <span aria-hidden="true" className="brand-tile" style={{ width: size, height: size }}>
      <Factory size={Math.round(size * 0.56)} strokeWidth={1.9} />
      <span className="brand-tile-dot" />
    </span>
  )
}
