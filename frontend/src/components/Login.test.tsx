// The sign-in form: it gets the CSRF cookie first, posts the user and password as JSON with the
// X-CSRFToken header, and shows the friendly message when they do not match.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { fakeFetch } from '../test/fakeFetch'
import Login from './Login'

function fill(username: string, password: string) {
  fireEvent.change(screen.getByLabelText('User ID'), { target: { value: username } })
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: password } })
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
}

describe('Login', () => {
  it('signs in with the CSRF token and tells the app', async () => {
    const fetch = fakeFetch({
      '/api/csrf': { body: { csrfToken: 'token-123' } },
      '/api/login': { body: { username: 'asha', is_staff: false, csrfToken: 'token-456' } },
    })
    const onSignedIn = vi.fn()

    render(<Login onSignedIn={onSignedIn} />)
    fill('asha', 'Test-pass-123')

    await waitFor(() => expect(onSignedIn).toHaveBeenCalledTimes(1))
    const [url, init] = fetch.mock.calls[fetch.mock.calls.length - 1]
    expect(url).toBe('/api/login')
    expect(init).toMatchObject({ method: 'POST', credentials: 'include' })
    expect((init!.headers as Record<string, string>)['X-CSRFToken']).toBe('token-123')
    expect(JSON.parse(init!.body as string)).toEqual({ username: 'asha', password: 'Test-pass-123' })
  })

  it('shows the message when the user and password do not match', async () => {
    fakeFetch({
      '/api/csrf': { body: { csrfToken: 'token-123' } },
      '/api/login': { status: 400, body: { detail: 'User ID and password did not match - please try again.' } },
    })
    const onSignedIn = vi.fn()

    render(<Login onSignedIn={onSignedIn} />)
    fill('asha', 'wrong')

    expect(await screen.findByRole('alert')).toHaveTextContent('did not match')
    expect(onSignedIn).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Sign in' })).not.toBeDisabled() // can try again
  })
})
