// Memory: the user's saved memories with their date, adding one (the server's limits show as a message),
// deleting one, and "Delete all" only after "Are you sure?".
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { callsTo, fakeFetch } from '../test/fakeFetch'
import { renderAt } from '../test/render'
import type { Memory, MemoryList } from '../types'
import MemoryPage, { deleteAllQuestion } from './MemoryPage'

const EXPORT: Memory = { id: 2, text: 'I only work with export sales', question_id: 41,
  created_at: '2026-11-03T10:15:00+05:30', created_text: '03 Nov 2026 10:15 AM' }
const LAKHS: Memory = { id: 1, text: 'Always show amounts in lakhs', question_id: null,
  created_at: '2026-11-02T09:00:00+05:30', created_text: '02 Nov 2026 09:00 AM' }
const LIST: MemoryList = { memories: [EXPORT, LAKHS], limit: 20, max_chars: 300 }

afterEach(() => vi.restoreAllMocks())

describe('MemoryPage', () => {
  it('lists the memories with their date and says what memory does', async () => {
    fakeFetch({ '/api/memories': { body: LIST } })

    renderAt('/memory', <MemoryPage />)

    expect(await screen.findByText('I only work with export sales')).toBeInTheDocument()
    expect(screen.getByText('03 Nov 2026 10:15 AM')).toBeInTheDocument()
    expect(screen.getByText('Always show amounts in lakhs')).toBeInTheDocument()
    expect(screen.getByText('2 memories of 20')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'from a question' })).toHaveAttribute('href', '/q/41')
    expect(screen.getByText(/used in all your later chats/)).toBeInTheDocument()
    expect(screen.getByText(/never changes the safety rules/)).toBeInTheDocument()
  })

  it('says when nothing is saved yet', async () => {
    fakeFetch({ '/api/memories': { body: { ...LIST, memories: [] } } })

    renderAt('/memory', <MemoryPage />)

    expect(await screen.findByText('Nothing saved yet.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Delete all' })).not.toBeInTheDocument()
  })

  it('adds a memory, and shows the server message when it cannot be saved', async () => {
    let saved = false
    let tries = 0
    const fetch = fakeFetch({
      '/api/memories': (init) => {
        if (init?.method !== 'POST') return { body: saved ? LIST : { ...LIST, memories: [LAKHS] } }
        tries += 1
        if (tries === 1) return { status: 400, body: { detail: 'I already remember this: "Always show amounts in lakhs".' } }
        saved = true
        return { body: { memory: EXPORT, message: 'Got it - I will remember: "I only work with export sales".' } }
      },
    })

    renderAt('/memory', <MemoryPage />)
    const box = await screen.findByLabelText('New memory')
    fireEvent.change(box, { target: { value: 'always show amounts in lakhs' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add' }))
    expect(await screen.findByText(/I already remember this/)).toHaveClass('errbox')
    expect(box).toHaveValue('always show amounts in lakhs')                  // kept to fix it

    fireEvent.change(box, { target: { value: 'I only work with export sales' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add' }))
    expect(await screen.findByText(/Got it - I will remember/)).toHaveClass('okbox')
    expect(await screen.findByText('I only work with export sales')).toBeInTheDocument()
    expect(box).toHaveValue('')
    expect(callsTo(fetch, '/api/memories')).toEqual([{ text: 'always show amounts in lakhs' },
                                                     { text: 'I only work with export sales' }])
  })

  it('deletes one memory', async () => {
    let deleted = false
    const fetch = fakeFetch({
      '/api/memories': { body: LIST },
      '/api/memories/2/delete': () => {
        deleted = true
        return { body: { deleted: 1, message: 'Forgotten: "I only work with export sales".' } }
      },
    })

    renderAt('/memory', <MemoryPage />)
    fireEvent.click(await screen.findByRole('button', { name: 'Delete "I only work with export sales"' }))

    expect(await screen.findByText('Forgotten: "I only work with export sales".')).toHaveClass('okbox')
    expect(deleted).toBe(true)
    expect(callsTo(fetch, '/api/memories/2/delete')).toEqual([{}])
  })

  it('deletes all only after "Are you sure?"', async () => {
    const fetch = fakeFetch({
      '/api/memories': { body: LIST },
      '/api/memories/delete-all': { body: { deleted: 2, message: 'All 2 memories were deleted.' } },
    })
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)

    renderAt('/memory', <MemoryPage />)
    const button = await screen.findByRole('button', { name: 'Delete all' })
    fireEvent.click(button)
    expect(confirm).toHaveBeenCalledWith(deleteAllQuestion(2))
    expect(callsTo(fetch, '/api/memories/delete-all')).toEqual([])             // "Cancel": nothing deleted

    fireEvent.click(button)
    expect(await screen.findByText('All 2 memories were deleted.')).toHaveClass('okbox')
    await waitFor(() => expect(callsTo(fetch, '/api/memories/delete-all')).toEqual([{}]))
    expect(deleteAllQuestion(2)).toBe('Delete all 2 memories? Your next questions will no longer use them. This cannot be undone.')
  })

  it('cannot add more when the memory is full', async () => {
    const many = Array.from({ length: 20 }, (_, i) => ({ ...LAKHS, id: i + 1, text: `Fact ${i + 1}` }))
    fakeFetch({ '/api/memories': { body: { ...LIST, memories: many } } })

    renderAt('/memory', <MemoryPage />)

    expect(await screen.findByText('Your memory is full - delete some memories first.')).toBeInTheDocument()
    expect(screen.getByLabelText('New memory')).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Add' })).toBeDisabled()
  })
})
