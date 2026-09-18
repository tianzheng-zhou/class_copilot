import { defineConfig } from '@playwright/test'
export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 30000,
  use: {
    baseURL: 'http://127.0.0.1:29039',
    headless: true,
    locale: 'zh-CN',
    viewport: { width: 1440, height: 1000 },
    trace: 'retain-on-failure',
  },
  webServer: {
    command: '../backend/.venv/bin/python ../scripts/browser_server.py',
    url: 'http://127.0.0.1:29039/api/v1/health',
    reuseExistingServer: false,
    timeout: 30000,
  },
})
