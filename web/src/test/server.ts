import { setupServer } from 'msw/node';

/** MSW server; tests add handlers with fixtures typed from the generated API types (src/test/fixtures.ts). */
export const server = setupServer();
