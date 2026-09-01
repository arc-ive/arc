import { describe, it, expect } from 'vitest'
import { ApiError, toApiError, errorMessage } from './errors.js'

describe('ApiError', () => {
  it('creates an error with default values', () => {
    const error = new ApiError('test message')
    expect(error.message).toBe('test message')
    expect(error.name).toBe('ApiError')
    expect(error.status).toBeNull()
    expect(error.detail).toBeNull()
    expect(error.isNetwork).toBe(false)
  })

  it('creates an error with custom values', () => {
    const error = new ApiError('not found', { status: 404, detail: 'Resource not found' })
    expect(error.status).toBe(404)
    expect(error.detail).toBe('Resource not found')
  })

  it('identifies unauthorized errors', () => {
    expect(new ApiError('unauthorized', { status: 401 }).isUnauthorized).toBe(true)
    expect(new ApiError('forbidden', { status: 403 }).isUnauthorized).toBe(false)
  })

  it('identifies forbidden errors', () => {
    expect(new ApiError('forbidden', { status: 403 }).isForbidden).toBe(true)
    expect(new ApiError('not found', { status: 404 }).isForbidden).toBe(false)
  })

  it('identifies not found errors', () => {
    expect(new ApiError('not found', { status: 404 }).isNotFound).toBe(true)
    expect(new ApiError('bad request', { status: 400 }).isNotFound).toBe(false)
  })

  it('identifies validation errors', () => {
    expect(new ApiError('bad request', { status: 400 }).isValidation).toBe(true)
    expect(new ApiError('server error', { status: 500 }).isValidation).toBe(false)
  })
})

describe('toApiError', () => {
  it('returns ApiError unchanged', () => {
    const original = new ApiError('test')
    expect(toApiError(original)).toBe(original)
  })

  it('converts network error (no response)', () => {
    const axiosError = { isAxiosError: true, response: null }
    const result = toApiError(axiosError)
    expect(result).toBeInstanceOf(ApiError)
    expect(result.isNetwork).toBe(true)
    expect(result.message).toContain('unreachable')
  })

  it('converts axios error with response', () => {
    const axiosError = {
      isAxiosError: true,
      response: { status: 403, data: { detail: 'Access denied' } },
    }
    const result = toApiError(axiosError)
    expect(result.status).toBe(403)
    expect(result.detail).toBe('Access denied')
  })

  it('converts unknown error', () => {
    const result = toApiError(new Error('something'))
    expect(result).toBeInstanceOf(ApiError)
    expect(result.message).toBe('something')
  })
})

describe('errorMessage', () => {
  it('extracts message from ApiError', () => {
    expect(errorMessage(new ApiError('test'))).toBe('test')
  })

  it('extracts message from axios error', () => {
    const axiosError = {
      isAxiosError: true,
      response: { status: 500, data: { detail: 'Server error' } },
    }
    expect(errorMessage(axiosError)).toBe('Server error')
  })

  it('extracts message from unknown error', () => {
    expect(errorMessage(new Error('oops'))).toBe('oops')
  })

  it('returns default for null/undefined', () => {
    expect(errorMessage(null)).toBe('Something went wrong')
    expect(errorMessage(undefined)).toBe('Something went wrong')
  })
})
