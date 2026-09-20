export const ACCEPTED_IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/webp']
export const DEFAULT_MAX_UPLOAD_BYTES = 8 * 1024 * 1024

function configuredMaximum() {
  const value = Number(import.meta.env.VITE_MAX_UPLOAD_BYTES)
  return Number.isFinite(value) && value > 0 ? value : DEFAULT_MAX_UPLOAD_BYTES
}

function apiBaseUrl() {
  return String(import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')
}

export function isAnalysisEnabled() {
  const value = String(import.meta.env.VITE_ANALYSIS_ENABLED ?? 'true').trim().toLowerCase()
  return !['false', '0', 'off', 'no'].includes(value)
}

export function validateImage(file, maximum = configuredMaximum()) {
  if (!file) return 'Choose a food-label image to continue.'
  if (!ACCEPTED_IMAGE_TYPES.includes(file.type)) {
    return 'Use a JPEG, PNG, or WEBP image.'
  }
  if (file.size === 0) return 'The selected image is empty.'
  if (file.size > maximum) {
    return `The image must be smaller than ${formatBytes(maximum)}.`
  }
  return null
}

export function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export async function analyzeImage(file, fetchImplementation = fetch) {
  if (!isAnalysisEnabled()) {
    throw new Error('Image analysis is disabled by the application configuration.')
  }
  const validationError = validateImage(file)
  if (validationError) throw new Error(validationError)

  const body = new FormData()
  body.append('image', file)
  let response
  try {
    response = await fetchImplementation(`${apiBaseUrl()}/api/v1/analyze`, {
      method: 'POST',
      body,
    })
  } catch {
    throw new Error('The analysis service could not be reached. Check that the backend is running.')
  }

  let payload
  try {
    payload = await response.json()
  } catch {
    throw new Error(`The analysis service returned an unreadable response (HTTP ${response.status}).`)
  }
  if (!response.ok) {
    throw new Error(
      payload?.error?.message || payload?.detail || `Analysis failed with HTTP ${response.status}.`,
    )
  }
  return payload
}
