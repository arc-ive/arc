import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ErrorState } from './ErrorState.jsx'
import { ApiError } from '../../api/errors.js'

describe('ErrorState', () => {
  it('renders explicit title and message when provided', () => {
    render(<ErrorState title="Custom Title" message="Custom message" />)
    expect(screen.getByText('Custom Title')).toBeInTheDocument()
    expect(screen.getByText('Custom message')).toBeInTheDocument()
  })

  it('derives title and message from ApiError when not provided', () => {
    const error = new ApiError('Resource not found', { status: 404 })
    render(<ErrorState error={error} />)
    expect(screen.getByText('Something went wrong')).toBeInTheDocument()
    expect(screen.getByText('Resource not found')).toBeInTheDocument()
  })

  it('shows "Permission denied" title for 403 errors', () => {
    const error = new ApiError('Access denied', { status: 403 })
    render(<ErrorState error={error} />)
    expect(screen.getByText('Permission denied')).toBeInTheDocument()
    expect(screen.getByText('Access denied')).toBeInTheDocument()
  })

  it('derives message from AxiosError when not provided', () => {
    const axiosError = {
      isAxiosError: true,
      response: { status: 500, data: { detail: 'Internal server error' } },
    }
    render(<ErrorState error={axiosError} />)
    expect(screen.getByText('Something went wrong')).toBeInTheDocument()
    expect(screen.getByText('Internal server error')).toBeInTheDocument()
  })

  it('shows network error message for AxiosError with no response', () => {
    const axiosError = { isAxiosError: true, response: null }
    render(<ErrorState error={axiosError} />)
    expect(screen.getByText('Something went wrong')).toBeInTheDocument()
    expect(screen.getByText(/unreachable/i)).toBeInTheDocument()
  })

  it('renders fallback message when no error, title, or message provided', () => {
    render(<ErrorState />)
    expect(screen.getByText('Something went wrong')).toBeInTheDocument()
    expect(screen.getByText('An unexpected error occurred.')).toBeInTheDocument()
  })

  it('renders retry button when onRetry is provided', () => {
    let clicked = false
    render(<ErrorState title="Error" message="msg" onRetry={() => { clicked = true }} />)
    const button = screen.getByRole('button', { name: /try again/i })
    button.click()
    expect(clicked).toBe(true)
  })

  it('does not render retry button when onRetry is not provided', () => {
    render(<ErrorState title="Error" message="msg" />)
    expect(screen.queryByRole('button', { name: /try again/i })).not.toBeInTheDocument()
  })
})
