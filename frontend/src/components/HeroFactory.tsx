// The small machine drawing on the right of the Home welcome banner (HomeHero.tsx): three meshing gears and a
// working pump - liquid comes in through the inlet pipe, the impeller turns inside the round housing and the liquid
// goes out through the outlet pipe, past a small pressure gauge. The company makes pumps, so the banner shows one.
// Thin white lines only (no fills), faint, so the white text next to it keeps its contrast; only for the eye
// (aria-hidden, no clicks).
// It moves only when motion is fine: the movement classes are set only then (motion = true), and HeroFactory.css
// moves them only inside the banner's "mi-hero-motion" and when the browser does not ask for less motion. With less
// motion the drawing simply stands still. Where the banner is too narrow for it (the clock no longer sits on the
// right), HeroFactory.css hides it.
import type { CSSProperties } from 'react'
import './HeroFactory.css'

/** A number for an SVG path, short (2 decimals). */
function n(value: number): string {
  return String(Math.round(value * 100) / 100)
}

/** The point at a radius and an angle (degrees, 0 = to the right, turning clockwise on the screen). */
function at(radius: number, degrees: number): string {
  const a = (degrees * Math.PI) / 180
  return `${n(radius * Math.cos(a))} ${n(radius * Math.sin(a))}`
}

/** The outline of a gear around (0, 0): `teeth` teeth on a pitch circle of radius `pitch` (module = tooth size).
 *  A tooth is a trapezoid: wide at its foot, narrow at its tip; the first tooth points to the right. */
export function gearPath(teeth: number, pitch: number, module: number): string {
  const tip = pitch + module
  const root = pitch - 1.25 * module
  const step = 360 / teeth
  let d = ''
  for (let i = 0; i < teeth; i += 1) {
    const c = i * step
    d += `${i === 0 ? 'M' : 'L'}${at(root, c - 0.3 * step)} L${at(tip, c - 0.14 * step)} `
    d += `A${n(tip)} ${n(tip)} 0 0 1 ${at(tip, c + 0.14 * step)} L${at(root, c + 0.3 * step)} `
    d += `A${n(root)} ${n(root)} 0 0 1 ${at(root, c + 0.7 * step)} `
  }
  return `${d}Z`
}

/** How far the second gear is turned at the start so that its teeth sit in the gaps of the first one.
 *  `angle` is the direction from the first gear's centre to the second's (degrees, clockwise on the screen). */
export function meshTurn(teethA: number, turnA: number, teethB: number, angle: number): number {
  const stepA = 360 / teethA
  const stepB = 360 / teethB
  // where the two gears touch: the first gear's tooth phase there, and the second gear needs half a tooth off it
  const phaseA = (angle - turnA) / stepA
  const turn = stepB * (phaseA + (angle + 180) / stepB - 0.5)
  return Math.round((((turn % stepB) + stepB) % stepB) * 100) / 100
}

const MODULE = 4 // the tooth size of all three gears (so they mesh)

type Gear = { teeth: number; x: number; y: number; turn: number; seconds: number; clockwise: boolean }

/** The three gears: a big one (15 teeth) driving a smaller one above (10 teeth) and a small one below (8 teeth).
 *  The time of one turn goes with the number of teeth (15 : 10 : 8 = 12 s : 8 s : 6.4 s), so the teeth move at the
 *  same speed where they touch and the gears look meshed; the two small ones turn the other way. */
function gears(): Gear[] {
  const big = { teeth: 15, x: 38, y: 58, turn: 0, seconds: 12, clockwise: true }
  const place = (teeth: number, angle: number): Gear => {
    const distance = (MODULE * (big.teeth + teeth)) / 2 // the two pitch circles touch
    const a = (angle * Math.PI) / 180
    return { teeth, x: Math.round((big.x + distance * Math.cos(a)) * 100) / 100,
      y: Math.round((big.y + distance * Math.sin(a)) * 100) / 100,
      turn: meshTurn(big.teeth, big.turn, teeth, angle), seconds: (big.seconds * teeth) / big.teeth, clockwise: false }
  }
  return [big, place(10, -32), place(8, 35)]
}

const GEARS = gears()

/** The pump housing: a volute (a snail shell) around the impeller, its radius growing from 23 to 30 clockwise
 *  round from the top, ending in the outlet pipe going out to the right at the top. */
function volutePath(): string {
  let d = ''
  for (let deg = 0; deg <= 360; deg += 10) {
    const r = 23 + (7 * deg) / 360
    d += `${deg === 0 ? 'M' : 'L'}${at(r, deg - 90)} `
  }
  return d.trim()
}

/** One impeller blade: from the hub out to the rim, curved back against the turning (clockwise) direction. */
function bladePath(degrees: number): string {
  return `M${at(5, degrees)} Q${at(13, degrees - 12)} ${at(18, degrees - 48)}`
}

const PUMP = { x: 214, y: 62 }
const BLADES = [0, 72, 144, 216, 288]
const GAUGE = { x: 262, y: 15 }
const TICKS = [-120, -80, -40, 0, 40, 80, 120]

/** A turning part's time and direction (read by HeroFactory.css). */
function turning(seconds: number, clockwise: boolean): CSSProperties {
  return { '--mi-turn': `${seconds}s`, '--mi-dir': clockwise ? 'normal' : 'reverse' } as CSSProperties
}

export default function HeroFactory({ motion }: { motion: boolean }) {
  const moves = (name: string) => (motion ? name : undefined)
  return (
    <div aria-hidden="true" data-slot="hero-factory" className="mi-factory">
      <svg viewBox="0 0 300 110" preserveAspectRatio="xMaxYMid meet" focusable="false" fill="none" stroke="#fff"
        strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round">
        {/* the gears: each one's outline, a hub and a few holes (so the turning shows) */}
        <g>
          {GEARS.map((gear) => {
            const pitch = (MODULE * gear.teeth) / 2
            const holes = gear.teeth >= 10 ? 5 : 4
            return (
              <g key={gear.teeth} transform={`translate(${gear.x} ${gear.y}) rotate(${gear.turn})`}>
                <g data-part="gear" data-teeth={gear.teeth} data-seconds={gear.seconds}
                  className={moves('mi-factory-turn')} style={turning(gear.seconds, gear.clockwise)}>
                  <path d={gearPath(gear.teeth, pitch, MODULE)} strokeOpacity=".48" />
                  <circle r={n(pitch * 0.24)} strokeOpacity=".4" />
                  <circle r="1.6" fill="#fff" fillOpacity=".35" stroke="none" />
                  {Array.from({ length: holes }, (_, i) => {
                    const [hx, hy] = at(pitch * 0.58, (360 / holes) * i + 18).split(' ')
                    return <circle key={i} cx={hx} cy={hy} r={n(pitch * 0.12)} strokeOpacity=".35" />
                  })}
                </g>
              </g>
            )
          })}
        </g>

        {/* the pipes: the inlet coming in from the left, the outlet going out to the right at the top, a flange at
            each joint; the liquid in them is a dashed line flowing in -> pump -> out */}
        <g strokeOpacity=".45">
          <path d="M116 58 H186 M116 66 H186 M116 54 V70 M186 54 V70" />
          <path d="M214 32 H296 M214 39 H296 M244 28.5 V42.5 M296 28.5 V42.5" />
        </g>
        <g strokeOpacity=".55" strokeWidth="1.4">
          <path data-part="flow-in" d="M118 62 H190" strokeDasharray="5 7" className={moves('mi-factory-flow')} />
          <path data-part="flow-out" d="M222 35.5 H294" strokeDasharray="5 7" className={moves('mi-factory-flow')} />
        </g>
        {/* a small bubble carried along the outlet pipe */}
        <circle cx="250" cy="35.5" r="1.5" strokeOpacity=".5" className={moves('mi-factory-bubble')} />

        {/* the pump: the housing on its stand, the impeller inside turning steadily, a small status light */}
        <g data-part="pump" transform={`translate(${PUMP.x} ${PUMP.y})`} strokeOpacity=".5">
          <path d={volutePath()} />
          <path d="M-10 24 L-15 34 M10 24 L15 34 M-28 34 H28" />
          <g data-part="impeller" data-seconds="4" className={moves('mi-factory-turn')} style={turning(4, true)}>
            <circle r="18" strokeOpacity=".28" />
            <circle r="5" />
            {BLADES.map((deg) => <path key={deg} d={bladePath(deg)} />)}
          </g>
          <circle data-part="status-light" cx="22" cy="30" r="1.8" fill="#fff" fillOpacity=".7" stroke="none"
            className={moves('mi-factory-light')} />
        </g>

        {/* the pressure gauge on the outlet pipe: its dial, a few marks and the needle, swaying gently */}
        <g data-part="gauge" transform={`translate(${GAUGE.x} ${GAUGE.y})`} strokeOpacity=".5">
          <path d="M-1.5 17 V10.4 M1.5 17 V10.4" />
          <circle r="10.5" />
          {TICKS.map((deg) => <path key={deg} d={`M${at(8.2, deg - 90)} L${at(9.6, deg - 90)}`} strokeOpacity=".4" />)}
          <path data-part="gauge-needle" d="M0 1.5 V-7.2" strokeWidth="1.3" strokeOpacity=".65"
            className={`mi-factory-needle${motion ? ' mi-factory-sway' : ''}`} />
          <circle r="1.4" fill="#fff" fillOpacity=".6" stroke="none" />
        </g>
      </svg>
    </div>
  )
}
