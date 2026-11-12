// The light / dark look: light by default, the choice is kept in this browser and shown as <html data-theme>.
import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { applyTheme, readTheme, useTheme } from './theme'

afterEach(() => {
  delete document.documentElement.dataset.theme
})

describe('theme', () => {
  it('is light when nothing is saved, or when something odd is saved', () => {
    expect(readTheme()).toBe('light')
    window.localStorage.setItem('mi.theme', 'purple')
    expect(readTheme()).toBe('light')
    window.localStorage.setItem('mi.theme', 'dark')
    expect(readTheme()).toBe('dark')
  })

  it('applyTheme sets <html data-theme> and saves the choice', () => {
    applyTheme('dark')
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(window.localStorage.getItem('mi.theme')).toBe('dark')

    applyTheme('light')
    expect(document.documentElement.dataset.theme).toBe('light')
    expect(window.localStorage.getItem('mi.theme')).toBe('light')
  })

  it('works without storage: light, and the page still changes', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked') })
    expect(readTheme()).toBe('light')
    expect(() => applyTheme('dark')).not.toThrow()
    expect(document.documentElement.dataset.theme).toBe('dark')
  })

  it('useTheme starts with the saved choice and its toggle flips it everywhere', () => {
    window.localStorage.setItem('mi.theme', 'dark')
    const first = renderHook(() => useTheme())
    const second = renderHook(() => useTheme())
    expect(first.result.current[0]).toBe('dark')

    act(() => first.result.current[1]())
    expect(first.result.current[0]).toBe('light')
    expect(second.result.current[0]).toBe('light')                   // every user of the hook hears it
    expect(document.documentElement.dataset.theme).toBe('light')
    expect(window.localStorage.getItem('mi.theme')).toBe('light')

    act(() => second.result.current[1]())
    expect(first.result.current[0]).toBe('dark')
    expect(document.documentElement.dataset.theme).toBe('dark')
  })
})
