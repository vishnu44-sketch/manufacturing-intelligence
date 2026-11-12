// Render a page at an address, inside the app's router (as the website does).
import { render } from '@testing-library/react'
import type { ReactNode } from 'react'
import { RouterProvider } from '../router'
import type { Me } from '../types'

export const ASHA: Me = {
  username: 'asha', name: 'Asha', is_staff: false, max_question_chars: 1000,
  examples: ['Top 5 customers by invoice value in Aug 2026?', 'How many sales orders are open and what is their value?'],
}
export const BOSS: Me = { ...ASHA, username: 'boss', name: 'Boss', is_staff: true }

export function renderAt(path: string, ui: ReactNode) {
  window.history.pushState(null, '', path)
  return render(<RouterProvider>{ui}</RouterProvider>)
}
