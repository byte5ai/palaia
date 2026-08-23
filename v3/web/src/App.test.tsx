import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import App from './App'

describe('App', () => {
  it('renders the shell: brand, primary nav, and the home screen', async () => {
    render(<App />)

    const brandLink = screen.getByRole('link', { name: /palaia/i })
    expect(brandLink).toBeInTheDocument()
    expect(brandLink.textContent).toContain('v3')
    expect(screen.getByRole('navigation', { name: 'Primary' })).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: 'Primary' }).textContent).toContain('Home')
    expect(screen.getByRole('navigation', { name: 'Primary' }).textContent).toContain('Explorer')

    // The home screen's live-state card, before any SSE event has arrived.
    expect(await screen.findByText(/connecting to the hub/i)).toBeInTheDocument()
  })
})
