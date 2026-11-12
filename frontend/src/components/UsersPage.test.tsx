// Users: everyone with role and access, adding a person (the server's field messages show next to the
// fields), switching someone off, a new password, and what a staff member without rights sees.
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { callsTo, fakeFetch } from '../test/fakeFetch'
import { renderAt } from '../test/render'
import type { PeopleList, Person } from '../types'
import UsersPage from './UsersPage'

const ROOT: Person = { id: 1, username: 'root', name: 'Root Admin', first_name: 'Root', last_name: 'Admin', email: '',
  is_staff: true, is_superuser: true, is_active: true, last_login: '03 Nov 2026 09:00 AM', is_me: true }
const ASHA: Person = { id: 2, username: 'asha', name: 'asha', first_name: '', last_name: '', email: 'asha@example.com',
  is_staff: false, is_superuser: false, is_active: true, last_login: '', is_me: false }
const LIST: PeopleList = { people: [ASHA, ROOT], can_add: true, can_change: true, can_set_roles: true, admin_url: '/admin/auth/user/' }

describe('UsersPage', () => {
  it('lists everyone with their role, access and last sign-in', async () => {
    fakeFetch({ '/api/users': { body: LIST } })

    renderAt('/users', <UsersPage />)

    expect(await screen.findByText('Root Admin')).toBeInTheDocument()
    expect(screen.getByText('(you)')).toBeInTheDocument()
    expect(screen.getByText('SUPERUSER')).toBeInTheDocument()
    expect(screen.getByText('USER')).toBeInTheDocument()
    expect(screen.getByText('never')).toBeInTheDocument()
    expect(screen.getByText('no email')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open in admin' })).toHaveAttribute('href', '/admin/auth/user/')
    expect(screen.getByRole('button', { name: 'Switch off asha' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Switch off root' })).not.toBeInTheDocument()   // never yourself
  })

  it('adds a person and shows the server messages next to the fields', async () => {
    let tries = 0
    const fetch = fakeFetch({
      '/api/users': (init) => {
        if (init?.method !== 'POST') return { body: LIST }
        tries += 1
        return tries === 1
          ? { status: 400, body: { detail: 'Please correct the marked fields.',
                                   errors: { username: ['A user with that username already exists.'],
                                             password2: ['This password is too common.'] } } }
          : { body: { person: { ...ASHA, id: 3, username: 'kiran' }, message: '"kiran" can now sign in.' } }
      },
    })

    renderAt('/users', <UsersPage />)
    fireEvent.click(await screen.findByRole('button', { name: '+ Add a person' }))
    const form = screen.getByRole('form', { name: 'Add a person' })
    fireEvent.change(within(form).getByLabelText('User ID (sign-in name)'), { target: { value: 'asha' } })
    fireEvent.change(within(form).getByLabelText('Password'), { target: { value: 'password' } })
    fireEvent.change(within(form).getByLabelText('Password again'), { target: { value: 'password' } })
    fireEvent.click(within(form).getByLabelText(/Staff/))
    fireEvent.click(within(form).getByRole('button', { name: 'Add the person' }))

    expect(await screen.findByText('A user with that username already exists.')).toHaveClass('field-error')
    expect(screen.getByText('This password is too common.')).toHaveClass('field-error')
    expect(screen.getByRole('alert')).toHaveTextContent('Please correct the marked fields.')
    expect(callsTo(fetch, '/api/users')[0]).toMatchObject({ username: 'asha', password1: 'password', is_staff: true })

    fireEvent.change(within(form).getByLabelText('User ID (sign-in name)'), { target: { value: 'kiran' } })
    fireEvent.click(within(form).getByRole('button', { name: 'Add the person' }))

    expect(await screen.findByText('"kiran" can now sign in.')).toHaveClass('okbox')
    expect(screen.queryByRole('form', { name: 'Add a person' })).not.toBeInTheDocument()
  })

  it('switches a person off', async () => {
    const fetch = fakeFetch({
      '/api/users': { body: LIST },
      '/api/users/2/active': { body: { person: { ...ASHA, is_active: false }, message: '"asha" is switched off and cannot sign in.' } },
    })

    renderAt('/users', <UsersPage />)
    fireEvent.click(await screen.findByRole('button', { name: 'Switch off asha' }))

    expect(await screen.findByText('"asha" is switched off and cannot sign in.')).toBeInTheDocument()
    expect(callsTo(fetch, '/api/users/2/active')).toEqual([{ active: false }])
  })

  it('sets a new password', async () => {
    const fetch = fakeFetch({
      '/api/users': { body: LIST },
      '/api/users/2/password': { body: { person: ASHA, message: 'The password of "asha" was changed.' } },
    })

    renderAt('/users', <UsersPage />)
    fireEvent.click(await screen.findByRole('button', { name: 'New password for asha' }))
    const form = screen.getByRole('form', { name: 'New password for asha' })
    fireEvent.change(within(form).getByLabelText('Password'), { target: { value: 'Plant-visit-2026!' } })
    fireEvent.change(within(form).getByLabelText('Password again'), { target: { value: 'Plant-visit-2026!' } })
    fireEvent.click(within(form).getByRole('button', { name: 'Save' }))

    expect(await screen.findByText('The password of "asha" was changed.')).toBeInTheDocument()
    expect(callsTo(fetch, '/api/users/2/password')).toEqual([{ password1: 'Plant-visit-2026!', password2: 'Plant-visit-2026!' }])
  })

  it('changes the details of a person', async () => {
    const fetch = fakeFetch({
      '/api/users': { body: LIST },
      '/api/users/2': { body: { person: { ...ASHA, first_name: 'Asha' }, message: '"asha" was saved.' } },
    })

    renderAt('/users', <UsersPage />)
    fireEvent.click(await screen.findByRole('button', { name: 'Edit asha' }))
    const form = screen.getByRole('form', { name: 'Change asha' })
    fireEvent.change(within(form).getByLabelText('First name'), { target: { value: 'Asha' } })
    fireEvent.click(within(form).getByRole('button', { name: 'Save' }))

    expect(await screen.findByText('"asha" was saved.')).toBeInTheDocument()
    const sent = callsTo(fetch, '/api/users/2')[0]
    expect(sent).toMatchObject({ username: 'asha', first_name: 'Asha', email: 'asha@example.com' })
    expect(sent).not.toHaveProperty('password1')
  })

  it('shows no change buttons to staff without the rights', async () => {
    fakeFetch({ '/api/users': { body: { ...LIST, can_add: false, can_change: false, can_set_roles: false } } })

    renderAt('/users', <UsersPage />)

    await waitFor(() => expect(screen.getByText('Root Admin')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: '+ Add a person' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Edit/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Switch/ })).not.toBeInTheDocument()
  })
})
