// The picture behind the sign-in card (Login.tsx): a calm, faded "factory blueprint", drawn here so there is no
// photo or outside file. Three layers, each its own SVG:
//   - the grid: faint engineering squares like blueprint paper, over the whole page (minor and major lines);
//   - the skyline along the bottom: a water tank, two saw-tooth roofed halls, chimneys, a pipeline with two pumps,
//     a tower crane, two silos with a conveyor and a third hall - thin lines with a soft fill, on one ground line;
//   - three gears: a meshing pair in the top-right corner and one on the left, turning very slowly.
// Every line is drawn in currentColor and every fill comes from a CSS class, and the colours of those come from the
// theme variables (app.css, the login block), so the dark theme gets a dark-blue version by itself.
// It is only for the eye (aria-hidden, no clicks). The gears and the liquid in the pipe move only when the browser
// does not ask for less motion (app.css); otherwise the picture stands still.
// Sizes: the grid fills the page; the skyline is a wide strip (2400 x 300) anchored at the bottom centre that is cut
// at the sides on narrower screens, so it keeps its shape from a phone (360 px) to a wide monitor.
import type { CSSProperties } from 'react'
import { gearPath, meshTurn } from './HeroFactory'

const GROUND = 290 // the ground line of the skyline strip

/** A row of small windows from x0 to x1 (one every `step`), `w` x `h` each, their tops at `y`. */
function windows(x0: number, x1: number, y: number, w: number, h: number, step: number): string {
  let d = ''
  for (let x = x0; x + w <= x1; x += step) d += `M${x} ${y} h${w} v${h} h${-w} Z `
  return d.trim()
}

/** A hall with a saw-tooth roof: from x0, `teeth` teeth of `width`, the roof edge at `base`, each tooth `rise`
 *  higher (the steep glazed face on the left of each tooth, the slope going down to the right). */
function sawtoothHall(x0: number, teeth: number, width: number, base: number, rise: number): string {
  let d = `M${x0} ${GROUND} V${base} `
  for (let i = 0; i < teeth; i += 1) {
    const x = x0 + i * width
    d += `V${base - rise} L${x + width} ${base} `
  }
  return `${d}V${GROUND} Z`
}

/** The glass on the steep face of each roof tooth: a short line just inside it. */
function sawtoothGlass(x0: number, teeth: number, width: number, base: number, rise: number): string {
  let d = ''
  for (let i = 0; i < teeth; i += 1) {
    const x = x0 + i * width + 6
    d += `M${x} ${base - rise + 8} V${base - 3} `
  }
  return d.trim()
}

/** A lattice (a crane's mast or jib): two rails from (x0, y0) to (x1, y1), `gap` apart, with a zigzag between. */
function lattice(x0: number, y0: number, x1: number, y1: number, gap: number, segments: number): string {
  const dx = x1 - x0
  const dy = y1 - y0
  const length = Math.hypot(dx, dy)
  const nx = (-dy / length) * gap // the second rail sits this far to the side
  const ny = (dx / length) * gap
  let d = `M${x0} ${y0} L${x1} ${y1} M${x0 + nx} ${y0 + ny} L${x1 + nx} ${y1 + ny} `
  for (let i = 0; i < segments; i += 1) {
    const a = i / segments
    const b = (i + 1) / segments
    const p = (t: number, side: boolean) =>
      `${Math.round((x0 + dx * t + (side ? nx : 0)) * 10) / 10} ${Math.round((y0 + dy * t + (side ? ny : 0)) * 10) / 10}`
    d += `M${p(a, i % 2 === 0)} L${p(b, i % 2 !== 0)} `
  }
  return d.trim()
}

/** A pump seen from the side: the round housing, its hub, the motor block on the right and the foot on the ground. */
function Pump({ x, y }: { x: number; y: number }) {
  return (
    <g transform={`translate(${x} ${y})`}>
      <path className="lb-fill" d="M-22 22 H48 V28 H-22 Z" />
      <path className="lb-fill" d="M14 -9 H42 V12 H14 Z M42 -5 h4 v13 h-4" />
      <circle className="lb-fill" r="17" />
      <circle className="lb-thin" r="11" />
      <circle r="4" />
      <path d="M-7 15 L-11 22 M7 15 L11 22 M20 -5 V8 M26 -5 V8 M32 -5 V8" className="lb-thin" />
    </g>
  )
}

// ------------------------------------------------------------------ the gears
const MODULE = 6 // the tooth size of the corner pair (so they mesh)

type Gear = { teeth: number; module: number; x: number; y: number; turn: number; seconds: number; clockwise: boolean }

/** The corner pair: a big gear (18 teeth) and a small one (11 teeth) meshing below-left of it. The time of one turn
 *  goes with the number of teeth, so the teeth move at the same speed where they touch. */
function cornerGears(): Gear[] {
  const big: Gear = { teeth: 18, module: MODULE, x: 0, y: 0, turn: 0, seconds: 96, clockwise: true }
  const angle = 125 // the small gear's direction from the big one (degrees, clockwise on the screen)
  const distance = (MODULE * (big.teeth + 11)) / 2
  const a = (angle * Math.PI) / 180
  const small: Gear = { teeth: 11, module: MODULE, x: Math.round(distance * Math.cos(a) * 100) / 100,
    y: Math.round(distance * Math.sin(a) * 100) / 100, turn: meshTurn(big.teeth, 0, 11, angle),
    seconds: (big.seconds * 11) / big.teeth, clockwise: false }
  return [big, small]
}

const CORNER_GEARS = cornerGears()
const SIDE_GEAR: Gear = { teeth: 14, module: 6, x: 0, y: 0, turn: 0, seconds: 120, clockwise: false }

/** A turning part's time and direction (read by the lb-turn class in app.css). */
function turning(seconds: number, clockwise: boolean): CSSProperties {
  return { '--lb-turn': `${seconds}s`, '--lb-dir': clockwise ? 'normal' : 'reverse' } as CSSProperties
}

/** One gear: its outline with a soft fill, a ring, the hub and a few round holes (so the turning shows). */
function GearShape({ gear }: { gear: Gear }) {
  const pitch = (gear.module * gear.teeth) / 2
  const holes = gear.teeth >= 14 ? 6 : 5
  return (
    <g transform={`translate(${gear.x} ${gear.y}) rotate(${gear.turn})`}>
      <g className="lb-turn" data-part="gear" style={turning(gear.seconds, gear.clockwise)}>
        <path className="lb-fill" d={gearPath(gear.teeth, pitch, gear.module)} />
        <circle className="lb-thin" r={Math.round(pitch * 0.78)} />
        <circle r={Math.round(pitch * 0.24)} />
        <circle className="lb-thin" r={Math.round(pitch * 0.1)} />
        {Array.from({ length: holes }, (_, i) => {
          const angle = ((360 / holes) * i * Math.PI) / 180
          const r = pitch * 0.52
          return <circle key={i} className="lb-thin" cx={Math.round(r * Math.cos(angle) * 10) / 10}
            cy={Math.round(r * Math.sin(angle) * 10) / 10} r={Math.round(pitch * 0.12 * 10) / 10} />
        })}
      </g>
    </g>
  )
}

// ------------------------------------------------------------------ the pipeline
// The liquid runs: in from the left -> pump 1 -> up and along the rack in front of the middle hall -> down into
// pump 2 -> up and into the first silo. One centre line; app.css draws it as a hollow tube (a wide stroke with a
// narrower one in the fill colour on top) and the moving dashes inside.
const PIPE = 'M812 262 H884 M900 245 V230 H1538 Q1548 230 1548 240 V262 H1564 M1580 245 V198 H1790'
const FLANGES = 'M832 254 V270 M1000 222 V238 M1200 222 V238 M1400 222 V238 M1548 246 V254 M1680 190 V206'
const RACK = [980, 1100, 1220, 1340, 1460] // the posts that hold the pipe up

export default function LoginBackground() {
  return (
    <div className="login-bg" aria-hidden="true" data-slot="login-background">
      {/* the blueprint paper: small squares, every fifth line a little stronger */}
      <svg className="lb-grid" focusable="false" width="100%" height="100%">
        <defs>
          <pattern id="lb-grid-minor" width="24" height="24" patternUnits="userSpaceOnUse">
            <path className="lb-grid-minor" d="M24 0 H0 V24" />
          </pattern>
          <pattern id="lb-grid-major" width="120" height="120" patternUnits="userSpaceOnUse">
            <rect width="120" height="120" fill="url(#lb-grid-minor)" />
            <path className="lb-grid-major" d="M120 0 H0 V120" />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#lb-grid-major)" />
      </svg>

      {/* the gears: a meshing pair in the top-right corner, one on the left */}
      <svg className="lb-gears lb-gears-corner" viewBox="-96 -66 162 182" focusable="false" fill="none" stroke="currentColor">
        {CORNER_GEARS.map((gear) => <GearShape key={gear.teeth} gear={gear} />)}
      </svg>
      <svg className="lb-gears lb-gears-side" viewBox="-52 -52 104 104" focusable="false" fill="none" stroke="currentColor">
        <GearShape gear={SIDE_GEAR} />
      </svg>

      {/* the factory skyline on its ground line */}
      <svg className="lb-skyline" viewBox="0 0 2400 300" preserveAspectRatio="xMidYMax slice" focusable="false"
        fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round">
        {/* water tank on its legs, and a small store beside it */}
        <path d="M80 290 L96 172 M150 290 L134 172 M88 232 H142 M92 200 L142 262 M138 200 L88 262" className="lb-thin" />
        <path className="lb-fill" d="M84 120 L115 100 L146 120 V172 H84 Z" />
        <path className="lb-thin" d="M84 138 H146 M84 155 H146 M115 100 V94" />
        <path className="lb-fill" d="M172 290 V226 H282 V290 Z" />
        <path className="lb-thin" d="M206 290 V256 H236 V290 M172 240 H282" />

        {/* hall 1: a saw-tooth roof, its windows and a roller door; a dimension line above it, like a drawing */}
        <path className="lb-fill" d={sawtoothHall(300, 5, 80, 200, 40)} />
        <path className="lb-thin" d={sawtoothGlass(300, 5, 80, 200, 40)} />
        <path className="lb-thin" d={windows(318, 600, 228, 24, 20, 40)} />
        <path className="lb-thin" d="M622 290 V244 H676 V290 M622 256 H676 M622 268 H676 M622 280 H676" />
        <path className="lb-dim" d="M300 134 H700 M300 128 V140 M700 128 V140 M300 134 l9 -3 v6 Z M700 134 l-9 -3 v6 Z" />

        {/* two chimneys with bands, a little smoke standing above the tall one */}
        <path className="lb-fill" d="M726 290 L736 62 H758 L768 290 Z" />
        <path className="lb-fill" d="M786 290 L792 104 H806 L812 290 Z" />
        <path className="lb-thin" d="M735 84 H759 M734 104 H760 M791 124 H807" />
        <g className="lb-smoke">
          <circle cx="752" cy="44" r="9" />
          <circle cx="768" cy="28" r="12" />
          <circle cx="790" cy="14" r="14" />
        </g>

        {/* hall 2 in the middle: a bigger saw-tooth hall with two rows of windows */}
        <path className="lb-fill" d={sawtoothHall(1000, 4, 110, 176, 46)} />
        <path className="lb-thin" d={sawtoothGlass(1000, 4, 110, 176, 46)} />
        <path className="lb-thin" d={`${windows(1022, 1430, 196, 28, 16, 46)} ${windows(1022, 1430, 248, 28, 16, 46)}`} />

        {/* the tower crane: mast, jib, the cab, the counterweight, the tie lines and the hook */}
        <path className="lb-thin" d={lattice(1500, 290, 1500, 66, 16, 14)} />
        <path className="lb-thin" d={lattice(1410, 50, 1800, 50, 8, 26)} />
        <path className="lb-fill" d="M1494 58 H1526 V76 H1494 Z M1416 58 H1448 V72 H1416 Z" />
        <path className="lb-thin" d="M1508 50 V20 M1508 20 L1416 50 M1508 20 L1790 50 M1712 58 V150 M1704 58 H1720" />
        <path d="M1712 150 v8 a6 6 0 1 1 -6 6" />

        {/* the pipeline: posts of the pipe rack, the tube with its flanges, the moving liquid, two pumps */}
        <path className="lb-thin" d={RACK.map((x) => `M${x} 236 V290`).join(' ')} />
        <path className="lb-pipe" d={PIPE} />
        <path className="lb-pipe-in" d={PIPE} />
        <path className="lb-flow" d={PIPE} />
        <path className="lb-thin" d={FLANGES} />
        <Pump x={900} y={GROUND - 28} />
        <Pump x={1580} y={GROUND - 28} />

        {/* two silos with domed tops, and a conveyor going up to them */}
        <path className="lb-fill" d="M1790 290 V122 Q1826 92 1862 122 V290 Z" />
        <path className="lb-fill" d="M1872 290 V142 Q1908 112 1944 142 V290 Z" />
        <path className="lb-thin" d="M1790 160 H1862 M1790 210 H1862 M1872 180 H1944 M1872 230 H1944" />
        <path className="lb-thin" d={lattice(2060, 282, 1918, 126, 7, 12)} />
        <path className="lb-thin" d="M2030 290 L2040 262 M2000 290 L2008 228" />

        {/* a third chimney and hall 3 on the right */}
        <path className="lb-fill" d="M2084 290 L2090 92 H2106 L2112 290 Z" />
        <path className="lb-thin" d="M2089 112 H2107" />
        <path className="lb-fill" d={sawtoothHall(2124, 3, 84, 212, 34)} />
        <path className="lb-thin" d={sawtoothGlass(2124, 3, 84, 212, 34)} />
        <path className="lb-thin" d={windows(2140, 2370, 238, 22, 18, 38)} />
        <path className="lb-fill" d="M2382 290 V244 H2400 V290 Z" />

        {/* the ground */}
        <path d="M0 290 H2400" />
        <path className="lb-dim" d="M0 297 H2400" />
      </svg>
    </div>
  )
}
