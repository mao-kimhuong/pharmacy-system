// API errors → the form field they belong to. Sources: `details.field` (+ `details.reason`, a translation key) from
// a service's own check, `details.errors[].loc` from request validation, and codes that always mean one field.
import { isApiError } from './errors';

export interface FieldError { reason: string }
export type FieldErrors = Record<string, FieldError>;

const NESTING = new Set(['body', 'promotion', 'cart']);

/** ["body", "promotion", "tiers", 0, "percent"] → "tiers" (the first name that is a form field). */
function fieldOf(loc: unknown[]): string | null {
  const name = loc.find((p) => typeof p === 'string' && !NESTING.has(p));
  return typeof name === 'string' ? name : null;
}

export function fieldErrors(error: unknown, byCode: Record<string, string> = {}): FieldErrors {
  if (!isApiError(error)) return {};
  const out: FieldErrors = {};
  const { field, reason, errors } = error.details as { field?: unknown; reason?: unknown; errors?: unknown };
  if (typeof field === 'string') out[field] = { reason: typeof reason === 'string' ? reason : 'invalid' };
  if (Array.isArray(errors)) {
    for (const e of errors as { loc?: unknown[]; type?: string }[]) {
      const name = fieldOf(e.loc ?? []);
      if (name && !out[name]) out[name] = { reason: e.type === 'missing' ? 'required' : 'invalid' };
    }
  }
  const coded = byCode[error.code];
  if (coded) out[coded] = { reason: error.code };
  return out;
}
