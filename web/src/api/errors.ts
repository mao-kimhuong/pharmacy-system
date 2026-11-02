// Every API error is ErrorOut {code, message, details}. ApiError carries it plus the HTTP status.
export interface ErrorOut {
  code: string;
  message: string;
  details?: Record<string, unknown>;
}

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: Record<string, unknown>;
  readonly requestId: string | null;

  constructor(code: string, message: string, status = 0, details: Record<string, unknown> = {}, requestId: string | null = null) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
    this.details = details;
    this.requestId = requestId;
  }

  static from(body: unknown, response: Response): ApiError {
    const requestId = response.headers.get('x-request-id');
    if (body && typeof body === 'object' && 'code' in body && typeof (body as ErrorOut).code === 'string') {
      const e = body as ErrorOut;
      return new ApiError(e.code, e.message ?? e.code, response.status, e.details ?? {}, requestId);
    }
    const code = response.status === 404 ? 'NOT_FOUND' : response.status === 403 ? 'FORBIDDEN' : response.status === 401
      ? 'NOT_AUTHENTICATED' : response.status === 429 ? 'RATE_LIMITED' : response.status === 503
      ? 'TEMPORARILY_UNAVAILABLE' : 'INTERNAL_ERROR';
    return new ApiError(code, response.statusText || code, response.status, {}, requestId);
  }

  /** Field errors of a 422 VALIDATION_ERROR, keyed by the last part of the location. */
  fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {};
    const errs = this.details.errors;
    if (Array.isArray(errs)) {
      for (const e of errs as { loc?: unknown[]; msg?: string }[]) {
        const loc = (e.loc ?? []).filter((x) => x !== 'body');
        const key = loc.map(String).join('.');
        if (key && e.msg) out[key] = e.msg;
      }
    }
    return out;
  }
}

export const isApiError = (e: unknown): e is ApiError => e instanceof ApiError;
