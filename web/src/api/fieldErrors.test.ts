import { describe, expect, it } from 'vitest';
import { ApiError } from './errors';
import { fieldErrors } from './fieldErrors';

describe('fieldErrors', () => {
  it('uses the field and reason of a service check', () => {
    const e = new ApiError('VALIDATION_ERROR', 'x', 422, { field: 'bundle_items', reason: 'bundle_min' });
    expect(fieldErrors(e)).toEqual({ bundle_items: { reason: 'bundle_min' } });
  });
  it('finds the field in request validation errors, under the body and the preview wrapper', () => {
    const e = new ApiError('VALIDATION_ERROR', 'x', 422, { errors: [
      { loc: ['body', 'promotion', 'tiers', 0, 'percent'], type: 'decimal_parsing' },
      { loc: ['body', 'name'], type: 'missing' },
    ] });
    expect(fieldErrors(e)).toEqual({ tiers: { reason: 'invalid' }, name: { reason: 'required' } });
  });
  it('maps codes that always mean one field', () => {
    expect(fieldErrors(new ApiError('DUPLICATE_CODE', 'x', 409), { DUPLICATE_CODE: 'code' })).toEqual({ code: { reason: 'DUPLICATE_CODE' } });
  });
  it('gives nothing for other errors', () => {
    expect(fieldErrors(new ApiError('TEMPORARILY_UNAVAILABLE', 'x', 503))).toEqual({});
    expect(fieldErrors(new Error('boom'))).toEqual({});
    expect(fieldErrors(null)).toEqual({});
  });
});
