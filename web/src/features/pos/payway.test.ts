import { describe, expect, it, vi } from 'vitest';
import { postToPayway } from './Payway';

describe('postToPayway', () => {
  it('posts the signed fields unchanged as multipart/form-data into the named window', () => {
    const submit = vi.spyOn(HTMLFormElement.prototype, 'submit').mockImplementation(function (this: HTMLFormElement) {
      expect(this.method).toBe('post');
      expect(this.enctype).toBe('multipart/form-data');
      expect(this.target).toBe('payway-checkout');
      expect(this.action).toBe('https://checkout-sandbox.payway.com.kh/api/payment-gateway/v1/payments/purchase');
      const got = Object.fromEntries(new FormData(this).entries());
      expect(got).toEqual({ tran_id: 'P1', amount: '0.9', hash: 'abc==' });
    });
    postToPayway({ action: 'https://checkout-sandbox.payway.com.kh/api/payment-gateway/v1/payments/purchase',
      fields: { tran_id: 'P1', amount: '0.9', hash: 'abc==' } }, 'payway-checkout');
    expect(submit).toHaveBeenCalledOnce();
    expect(document.querySelectorAll('form')).toHaveLength(0); // removed after posting
    submit.mockRestore();
  });
});
