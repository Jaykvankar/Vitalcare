import { defineConfig } from "@playwright/test";
import { resolve } from "node:path";

const port = process.env.RPM_E2E_PORT ?? "8010";
const python = resolve(process.cwd(), "..", ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const server = resolve(process.cwd(), "..", "scripts", "e2e_server.py");

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    // Locally use an installed Chrome (or RPM_E2E_CHANNEL=msedge); CI installs Chromium.
    channel: process.env.CI ? undefined : process.platform === "win32" ? (process.env.RPM_E2E_CHANNEL ?? "chrome") : undefined,
    trace: "retain-on-failure",
  },
  webServer: {
    command: `"${python}" "${server}"`,
    url: `http://127.0.0.1:${port}/api/health/ready`,
    timeout: 180_000,
    reuseExistingServer: false,
    env: { RPM_E2E_PORT: port },
  },
});
