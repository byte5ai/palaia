import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import App from './App'

describe('App', () => {
  it('renders the shell: wordmark, the five places plus Settings, and the Overview', async () => {
    render(<App />)

    expect(screen.getByRole('link', { name: /palaia, overview/i })).toBeInTheDocument()
    const primary = screen.getByRole('navigation', { name: 'Primary' })
    for (const place of ['Overview', 'Memories', 'AI apps', 'Add-ons', 'Automations', 'Settings']) {
      expect(primary.textContent).toContain(place)
    }

    // The Overview's verdict, before any live-state event has arrived.
    expect(await screen.findByText(/connecting to the hub/i)).toBeInTheDocument()
  })
})
