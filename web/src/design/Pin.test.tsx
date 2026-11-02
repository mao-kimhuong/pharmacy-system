import { useState } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setLang } from '@/i18n';
import { server } from '@/test/server';
import { renderPlain } from '@/test/render';
import { PinDialog, PinPad } from './Pin';

function Pad({ onComplete }: { onComplete: (v: string) => void }) {
  const [v, setV] = useState('');
  return <PinPad value={v} onChange={setV} onComplete={onComplete} length={6} />;
}

describe('PIN', () => {
  beforeEach(() => setLang('en'));

  it('takes digits from the keypad and the keyboard', async () => {
    const done = vi.fn();
    render(<Pad onComplete={done} />);
    await userEvent.click(screen.getByRole('button', { name: '1' }));
    await userEvent.keyboard('23456');
    expect(done).toHaveBeenCalledWith('123456');
  });

  it('verifies the PIN for an action and returns the one-time token', async () => {
    let body: unknown;
    server.use(http.post('*/api/auth/v1/pin/verify', async ({ request }) => {
      body = await request.json();
      return HttpResponse.json({ pin_token: 't1', expires_at: '2026-01-01T00:00:00Z', user_id: 'u', name: 'A' });
    }));
    const onToken = vi.fn();
    renderPlain(<PinDialog open action="controlled.dispense" onClose={() => {}} onToken={onToken} />);
    await userEvent.keyboard('123456');
    await vi.waitFor(() => expect(onToken).toHaveBeenCalledWith(expect.objectContaining({ pin_token: 't1' })));
    expect(body).toEqual({ pin: '123456', action: 'controlled.dispense' });
  });

  it('shows the tries left on a wrong PIN, and the lock time when locked', async () => {
    server.use(http.post('*/api/auth/v1/pin/verify', () => HttpResponse.json({ code: 'PIN_INVALID', message: 'Wrong PIN', details: { attempts_left: 3 } }, { status: 401 })));
    renderPlain(<PinDialog open action="a" onClose={() => {}} onToken={() => {}} />);
    await userEvent.keyboard('111111');
    expect(await screen.findByText(/\(3\)/)).toBeInTheDocument();
    server.use(http.post('*/api/auth/v1/pin/verify', () => HttpResponse.json({ code: 'PIN_LOCKED', message: 'x', details: { locked_until: '2026-10-31T07:22:00Z' } }, { status: 423 })));
    await userEvent.keyboard('222222');
    expect(await screen.findByText(/14:22/)).toBeInTheDocument();
  });
});
