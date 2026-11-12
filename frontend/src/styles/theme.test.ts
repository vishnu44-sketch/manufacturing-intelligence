// The colour contract of the app: styles/app.css holds every colour as a variable (light in :root, dark in
// :root[data-theme="dark"]) and tailwind.css maps the Tailwind / shadcn names to those variables. The css
// files are read from the disk as text: vitest runs with css off, so an import of a css file (also with
// ?raw) is empty. The project has no Node types, so Node's fs is loaded by a built name (it comes as "any").
import { describe, expect, it } from 'vitest'

const fs = await import(/* @vite-ignore */ `node:${'fs'}`)
const read = (path: string): string => fs.readFileSync(new URL(path, import.meta.url), 'utf8').replace(/\r\n/g, '\n')
const appCss = read('./app.css')
const tailwindCss = read('../tailwind.css')

// the variables ("--name" -> value) of the first block that starts with this selector
function variablesOf(css: string, selector: string): Map<string, string> {
  const start = css.indexOf(`${selector} {`)
  expect(start, `${selector} block`).toBeGreaterThanOrEqual(0)
  const block = css.slice(css.indexOf('{', start) + 1, css.indexOf('}', start)).replace(/\/\*[\s\S]*?\*\//g, '')
  const found = new Map<string, string>()
  for (const [, name, value] of block.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) found.set(name, value.trim())
  return found
}

// the value of one Tailwind colour token in the @theme block
function token(name: string): string | undefined {
  return tailwindCss.match(new RegExp(`--color-${name}:\\s*([^;]+);`))?.[1].trim()
}

const light = variablesOf(appCss, '\n:root')
const dark = variablesOf(appCss, ':root[data-theme="dark"]')

describe('the colour variables (styles/app.css)', () => {
  it('has the blue brand, and red only as danger', () => {
    expect(light.get('--brand')).toBe('#0B5FB3')
    expect(light.get('--brand2')).toBe('#094C91')
    expect(light.get('--brand-bg')).toBe('#E8F1FB')
    expect(light.get('--danger')).toBe('#C00000')
    expect(light.get('--danger-bg')).toBe('#FBE9E9')
  })

  it('keeps the old red names as other names of the brand', () => {
    expect(appCss).toContain('--red: var(--brand);')
    expect(appCss).toContain('--red2: var(--brand2);')
    expect(appCss).toContain('--red-bg: var(--brand-bg);')
  })

  it('gives every light variable a dark value', () => {
    expect(light.size).toBeGreaterThan(30)
    const missing = [...light.keys()].filter((name) => !dark.has(name))
    expect(missing).toEqual([])
    expect(dark.get('--brand')).not.toBe(light.get('--brand'))
    expect(dark.get('--bg')).not.toBe(light.get('--bg'))
    expect(dark.get('--surface')).not.toBe(light.get('--surface'))
    expect(dark.get('--ink')).not.toBe(light.get('--ink'))
  })

  it('tells the browser which scheme is on (form controls, scrollbars)', () => {
    expect(appCss).toMatch(/:root \{\s*color-scheme: light;/)
    expect(appCss).toMatch(/:root\[data-theme="dark"\] \{\s*color-scheme: dark;/)
  })

  it('has no hard-coded colour outside the two variable blocks', () => {
    const rules = appCss.slice(appCss.indexOf('* { box-sizing'))
    expect(rules.match(/#[0-9a-fA-F]{3,8}\b|rgba?\(/g) ?? []).toEqual([])
    for (const file of ['../extra.css', '../charts/chart.css']) {
      expect(read(file).match(/#[0-9a-fA-F]{3,8}\b|rgba?\(/g) ?? [], file).toEqual([])
    }
  })
})

describe('the Tailwind colour names (tailwind.css)', () => {
  it('has the dark: variant on data-theme', () => {
    expect(tailwindCss).toContain('@custom-variant dark (&:where([data-theme="dark"], [data-theme="dark"] *));')
  })

  it('maps primary to the brand and destructive to the real red', () => {
    expect(token('primary')).toBe('var(--brand)')
    expect(token('primary-soft')).toBe('var(--brand-bg)')
    expect(token('destructive')).toBe('var(--danger)')
    expect(token('danger-soft')).toBe('var(--danger-bg)')
  })

  it('has every name of the contract, each pointing to a variable that has a dark value', () => {
    const names = ['background', 'foreground', 'card', 'card-foreground', 'popover', 'popover-foreground',
      'primary', 'primary-foreground', 'primary-soft', 'secondary', 'secondary-foreground', 'muted',
      'muted-foreground', 'accent', 'accent-foreground', 'destructive', 'danger-soft', 'border', 'input', 'ring',
      'heading', 'faint', 'success', 'success-soft', 'warning', 'warning-soft', 'info', 'info-soft',
      'sidebar', 'sidebar-foreground', 'sidebar-muted', 'sidebar-accent']
    for (const name of names) {
      const variable = token(name)?.match(/^var\((--[\w-]+)\)$/)?.[1]
      expect(variable, `--color-${name}`).toBeDefined()
      expect(dark.has(variable!), `${name} -> ${variable} in dark`).toBe(true)
    }
  })
})
