// The stack's clock must agree with this machine's: the e2e 2FA codes are made here and checked by the
// auth service (one 30 s step either side). After the Mac sleeps, the Docker VM clock can fall behind
// and every 2FA login then fails as INVALID_MFA_CODE, which looks like an app bug. Checked first in seed.ts.

export const MAX_SKEW_SECONDS = 15;

/** null when the clocks agree; else the message to fail with. `serverDate` is the HTTP Date header. */
export function clockSkewProblem(serverDate: string | null, nowMs: number, baseUrl: string): string | null {
  const server = serverDate ? Date.parse(serverDate) : NaN;
  if (Number.isNaN(server)) return null; // no Date header: nothing to compare (the logins will tell)
  // the header has whole seconds: allow the second it was cut to
  const skew = Math.round((server - nowMs) / 1000);
  if (Math.abs(skew) <= MAX_SKEW_SECONDS) return null;
  const way = skew < 0 ? 'behind' : 'ahead of';
  return [
    `The stack's clock (${baseUrl}) is ${Math.abs(skew)} s ${way} this machine's (more than ${MAX_SKEW_SECONDS} s).`,
    'Every 2FA login would fail with INVALID_MFA_CODE. The Docker VM clock drifts when the Mac sleeps:',
    'resync it, then run again:',
    '  docker run --rm --privileged alpine hwclock -s     (or restart Docker Desktop)',
    'Run long suites under caffeinate (make web-e2e does) so the Mac does not sleep.',
  ].join('\n');
}

export async function checkServerClock(baseUrl: string): Promise<void> {
  const before = Date.now();
  const res = await fetch(`${baseUrl}/api/auth/v1/health`);
  const now = (before + Date.now()) / 2; // the middle of the round trip
  const problem = clockSkewProblem(res.headers.get('date'), now, baseUrl);
  if (problem) throw new Error(problem);
}
