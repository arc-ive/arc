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
    expect(new ApiError('unprocessable', { status: 422 }).isValidation).toBe(true)
    expect(new ApiError('server error', { status: 500 }).isValidation).toBe(false)
  })
})

describe('structured 422 validation detail', () => {
  const validationResponse = (detail) => ({
    isAxiosError: true,
    response: { status: 422, data: { detail } },
  })

  it('names the offending field instead of reporting only the status', () => {
    const message = errorMessage(
      validationResponse([
        { loc: ['body', 'name'], msg: 'Field required', type: 'missing' },
      ]),
    )
    expect(message).toBe('name: Field required')
    expect(message).not.toContain('status 422')
  })

  it('joins multiple field errors', () => {
    const message = errorMessage(
      validationResponse([
        { loc: ['body', 'id'], msg: 'Field required' },
        { loc: ['body', 'role'], msg: 'Input should be one of owner, member' },
      ]),
    )
    expect(message).toBe('id: Field required; role: Input should be one of owner, member')
  })

  it('reports nested locations with a path', () => {
    const message = errorMessage(
      validationResponse([
        { loc: ['body', 'previous_steps', 0, 'status'], msg: 'Input should be valid' },
      ]),
    )
    expect(message).toBe('previous_steps.0.status: Input should be valid')
  })

  it('falls back to the status when the list carries nothing usable', () => {
    expect(errorMessage(validationResponse([]))).toBe('Request failed with status 422')
    expect(errorMessage(validationResponse([{ loc: ['body'] }]))).toBe(
      'Request failed with status 422',
    )
  })

  it('still prefers a plain string detail when the API sends one', () => {
    const message = errorMessage({
      isAxiosError: true,
      response: { status: 403, data: { detail: 'Access denied' } },
    })
    expect(message).toBe('Access denied')
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
