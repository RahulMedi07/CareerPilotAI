import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';

/**
 * Node environment, not jsdom.
 *
 * The tests here cover the API layer and the display rules that decide whether
 * a figure is shown at all. None of that touches the DOM, and adding jsdom +
 * testing-library to render shadcn primitives would mostly assert that Radix
 * works, which is not this project's job to prove.
 */
export default defineConfig({
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./', import.meta.url)),
    },
  },
  test: {
    environment: 'node',
    include: ['__tests__/**/*.test.ts'],
  },
});
