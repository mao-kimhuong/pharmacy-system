import { defineConfig, devices } from '@playwright/test';

// Runs against a running stack (make up). BASE_URL may point at a throwaway stack.
export default defineConfig({
  testDir: './e2e',
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1, // one shared stack; logins are rate limited per phone (5/min)
  retries: process.env.CI ? 1 : 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  globalSetup: './e2e/seed.ts',
  use: {
    baseURL: process.env.BASE_URL ?? 'http://localhost',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    locale: 'en-GB',
    timezoneId: 'Asia/Phnom_Penh',
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1366, height: 768 } }, testIgnore: /\.mobile\.spec\.ts$/ },
    { name: 'mobile', use: { ...devices['Pixel 7'], viewport: { width: 390, height: 844 } }, testMatch: /\.mobile\.spec\.ts$/ },
  ],
});
