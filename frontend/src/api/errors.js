export class ApiError extends Error {
  constructor(message, { status = null, detail = null, isNetwork = false } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.isNetwork = isNetwork
  }

  get isUnauthorized() {
    return this.status === 401
  }

  get isForbidden() {
    return this.status === 403
  }

  get isNotFound() {
    return this.status === 404
  }

  get isValidation() {
    return this.status === 400
  }
}

export function toApiError(error) {
  if (error instanceof ApiError) return error
  if (error?.isAxiosError) {
    const response = error.response
    if (!response) {
      return new ApiError(
        'Network error. The API is unreachable.',
        { isNetwork: true },
      )
    }
    const detail = response.data?.detail ?? null
    const message =
      typeof detail === 'string' && detail
        ? detail
        : `Request failed with status ${response.status}`
    return new ApiError(message, {
      status: response.status,
      detail,
    })
  }
  return new ApiError(error?.message ?? 'Unknown error')
}

export function errorMessage(error) {
  if (error instanceof ApiError) return error.message
  if (error?.isAxiosError) return toApiError(error).message
  return error?.message ?? 'Something went wrong'
}