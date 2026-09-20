import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../src/App.jsx'
import { safeSourceUrl } from '../src/result-utils.js'
import { completeResponse, partialResponse } from './fixtures.js'

function response(payload, { ok = true, status = 200 } = {}) {
  return { ok, status, json: vi.fn().mockResolvedValue(payload) }
}

async function selectImage(user, file = new File(['label'], 'label.png', { type: 'image/png' })) {
  await user.upload(screen.getByTestId('image-input'), file)
  return file
}

describe('NutriLens analysis UI', () => {
  beforeEach(() => {
    global.fetch = vi.fn()
  })

  afterEach(() => vi.restoreAllMocks())

  it('allows only HTTPS citation destinations', () => {
    expect(safeSourceUrl('https://www.fssai.gov.in/example')).toBe('https://www.fssai.gov.in/example')
    expect(safeSourceUrl('http://example.test/source')).toBeNull()
    expect(safeSourceUrl('javascript:alert(1)')).toBeNull()
  })

  it('validates image type before making a request', async () => {
    const user = userEvent.setup({ applyAccept: false })
    render(<App />)
    await selectImage(user, new File(['not-image'], 'notes.txt', { type: 'text/plain' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Use a JPEG, PNG, or WEBP image.')
    expect(global.fetch).not.toHaveBeenCalled()
  })

  it('posts multipart image data to the stable endpoint and renders complete M1/M2/M5 output', async () => {
    global.fetch.mockResolvedValue(response(completeResponse))
    const user = userEvent.setup()
    render(<App />)
    const file = await selectImage(user)
    await user.click(screen.getByRole('button', { name: 'Analyze nutrition label' }))

    await screen.findByRole('heading', { name: 'Analysis complete' })
    expect(global.fetch).toHaveBeenCalledTimes(1)
    const [url, options] = global.fetch.mock.calls[0]
    expect(url).toBe('/api/v1/analyze')
    expect(options.method).toBe('POST')
    expect(options.body).toBeInstanceOf(FormData)
    expect(options.body.get('image')).toEqual(file)
    expect(screen.getByText('72/100')).toBeInTheDocument()
    expect(screen.getAllByText('MODERATE').length).toBeGreaterThan(0)
    expect(screen.getByText('Wheat flour')).toBeInTheDocument()
    expect(screen.getByText('Compare lower-sugar options.')).toBeInTheDocument()
    expect(screen.getByText('TF-IDF token attributions for the existing MODERATE prediction. These are model contributions, not ingredient-level medical causality.')).toBeInTheDocument()
  })

  it('renders verified RAG citation links and exact evidence excerpts', async () => {
    global.fetch.mockResolvedValue(response(completeResponse))
    const user = userEvent.setup()
    render(<App />)
    await selectImage(user)
    await user.click(screen.getByRole('button', { name: 'Analyze nutrition label' }))

    const citation = await screen.findByRole('link', { name: '[S1] FSSAI' })
    expect(citation).toHaveAttribute('href', 'https://www.fssai.gov.in/example')
    await user.click(screen.getByText('View evidence excerpts and source details'))
    expect(screen.getByText('Ingredients shall be listed in descending order.')).toBeInTheDocument()
  })

  it('keeps a clear loading state while the backend request is pending', async () => {
    let resolveRequest
    global.fetch.mockReturnValue(new Promise((resolve) => { resolveRequest = resolve }))
    const user = userEvent.setup()
    render(<App />)
    await selectImage(user)
    await user.click(screen.getByRole('button', { name: 'Analyze nutrition label' }))

    expect(screen.getByRole('button', { name: 'Analyzing label…' })).toBeDisabled()
    expect(screen.getByRole('status')).toHaveTextContent('Reading label')
    resolveRequest(response(completeResponse))
    await screen.findByRole('heading', { name: 'Analysis complete' })
  })

  it('keeps partial and unavailable components explicit without hiding available model output', async () => {
    global.fetch.mockResolvedValue(response(partialResponse))
    const user = userEvent.setup()
    render(<App />)
    await selectImage(user)
    await user.click(screen.getByRole('button', { name: 'Analyze nutrition label' }))

    await screen.findByRole('heading', { name: 'Partial analysis available' })
    expect(screen.getByText('M2 nutrition scoring requires a per_100g basis; no basis conversion was attempted.')).toBeInTheDocument()
    expect(screen.getAllByText('Knowledge base unavailable').length).toBeGreaterThan(0)
    expect(screen.getByText('SHAP is disabled')).toBeInTheDocument()
    expect(screen.getByText('Not enough source evidence')).toBeInTheDocument()
    expect(screen.getAllByText('MODERATE').length).toBeGreaterThan(0)
    expect(screen.getByText('M5 knowledge lookup is unavailable.')).toBeInTheDocument()
  })

  it('shows backend-safe error messages and does not fabricate results', async () => {
    global.fetch.mockResolvedValue(response({ status: 'error', error: { code: 'ocr_failed', message: 'Text could not be extracted from this image.' } }, { ok: false, status: 422 }))
    const user = userEvent.setup()
    render(<App />)
    await selectImage(user)
    await user.click(screen.getByRole('button', { name: 'Analyze nutrition label' }))

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Text could not be extracted from this image.'))
    expect(screen.queryByRole('heading', { name: /Analysis complete/i })).not.toBeInTheDocument()
  })

  it('reports a network failure while preserving the selected image for retry', async () => {
    global.fetch.mockRejectedValue(new TypeError('offline'))
    const user = userEvent.setup()
    render(<App />)
    await selectImage(user)
    await user.click(screen.getByRole('button', { name: 'Analyze nutrition label' }))

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('analysis service could not be reached'))
    expect(screen.getByText('label.png')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Analyze nutrition label' })).toBeEnabled()
  })
})
