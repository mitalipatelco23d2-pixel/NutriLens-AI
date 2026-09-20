import '@testing-library/jest-dom/vitest'

Object.defineProperty(URL, 'createObjectURL', {
  configurable: true,
  value: vi.fn(() => 'blob:label-preview'),
})
Object.defineProperty(URL, 'revokeObjectURL', {
  configurable: true,
  value: vi.fn(),
})
Element.prototype.scrollIntoView = vi.fn()
