import { execFileSync } from "node:child_process";
import { rmSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";
import { login, logout } from "./helpers";

const ROOT = resolve(process.cwd(), "..");
const PYTHON = resolve(ROOT, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const CLIENT = resolve(ROOT, "scripts", "device_client.py");
const SENSOR = resolve(ROOT, "scripts", "sensor_example.py");

test.describe.configure({ mode: "serial" });

test("clinician sees a risk-sorted worklist and acknowledges an alert", async ({ page }) => {
  await login(page, "dr.mehta");
  await expect(page.getByRole("heading", { name: "Patient worklist" })).toBeVisible();
  const rows = page.locator("table tbody tr");
  await expect(rows).toHaveCount(3);
  await rows.first().click();
  await expect(page.getByRole("heading", { name: "Patient record" })).toBeVisible();
  await expect(page.getByText("Vital signs over time")).toBeVisible();

  const ack = page.getByRole("button", { name: "Acknowledge" }).first();
  await expect(ack).toBeVisible();
  await ack.click();
  await page.getByPlaceholder("Note for the record (stored encrypted)").fill("Reviewed in e2e test");
  await page.getByRole("button", { name: "Confirm" }).click();
  await expect(page.getByText("Reviewed in e2e test")).toBeVisible();
  await logout(page);
});

test("clinician connects a real gateway with the wizard and sees readings arrive", async ({ page }) => {
  await login(page, "dr.mehta");
  await page.locator("table tbody tr").first().click();
  await page.getByRole("button", { name: "Connect device" }).click();

  // 1-2: choose the device type and name it
  await page.getByRole("button", { name: /Vitalcare gateway/ }).click();
  await page.getByLabel("Name shown in the device list").fill("E2E gateway");
  await page.getByRole("button", { name: "Create connection code" }).click();

  // 3: code, QR and the IT command with the pairing link
  const code = (await page.getByLabel("Pairing code").textContent())!.trim();
  expect(code).toMatch(/^[A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4}$/);
  await expect(page.getByLabel("Pairing QR code").locator("svg")).toBeVisible();
  await page.getByText("For IT staff: connect a gateway from the command line").click();
  const command = (await page.locator("pre.cmd").textContent())!;
  const link = command.match(/--link "([^"]+)"/)![1];
  expect(link).toContain(`code=${code}`);

  // A real gateway process pairs with the link and pipes three sensor readings
  const state = resolve(process.cwd(), "..", ".e2e", "gateway-state.json");
  rmSync(state, { force: true });
  const env = { ...process.env, RPM_DEVICE_PASSPHRASE: "e2e-gateway-passphrase" };
  execFileSync(PYTHON, [CLIENT, "pair", "--link", link, "--state", state], { env, cwd: ROOT });
  await expect(page.getByText("Connected.")).toBeVisible({ timeout: 15_000 });
  const readings = execFileSync(PYTHON, [SENSOR, "--count", "3", "--interval", "0"], { cwd: ROOT });
  const out = execFileSync(PYTHON, [CLIENT, "stream", "--source", "stdin", "--state", state], { env, cwd: ROOT, input: readings }).toString();
  expect(out.match(/^200 /gm)?.length).toBe(3);

  // 4: the wizard confirms, and the device list shows it as receiving
  await expect(page.getByText("Readings are arriving.")).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: "Close" }).click();
  await expect(page.getByText("E2E gateway")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("Receiving readings").first()).toBeVisible({ timeout: 15_000 });
  await logout(page);
});

test("everyone can open the device guide", async ({ page }) => {
  await login(page, "p.sharma");
  await page.getByRole("link", { name: "Help with devices" }).first().click();
  await expect(page.getByRole("heading", { name: "Connecting devices" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Fingertip pulse oximeter" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Will my device work?" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "For IT staff" })).toHaveCount(0);   // staff-only section hidden
  await logout(page);
});

test("admin onboards people from CSV and verifies the ledger", async ({ page }) => {
  await login(page, "admin");
  await page.goto("/admin/import");
  const csv = "username,full_name,role,dob,phone,address,care_team\n" +
    "dr.e2e,Dr E2E,clinician,,,,\n" +
    "p.e2e,Patient E2E,patient,1975-03-03,,,dr.e2e\n";
  await page.locator('input[type="file"]').setInputFiles({ name: "people.csv", mimeType: "text/csv", buffer: Buffer.from(csv) });
  await expect(page.getByText("2 ready · 0 with problems")).toBeVisible();
  await page.getByRole("button", { name: "Create 2 accounts" }).click();
  await expect(page.getByText(/Created 2 accounts/)).toBeVisible();

  await page.goto("/admin/audit");
  await page.getByRole("button", { name: "Verify integrity" }).click();
  await expect(page.getByText("Ledger intact.")).toBeVisible();
  await logout(page);
});

test("patient sees own data and can pause sharing", async ({ page }) => {
  await login(page, "p.sharma");
  await expect(page.getByRole("heading", { name: /Hello/ })).toBeVisible();
  await expect(page.getByText("Sharing with my care team")).toBeVisible();
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Pause sharing" }).click();
  await expect(page.getByRole("button", { name: "Resume sharing" })).toBeVisible();
  await page.getByRole("button", { name: "Resume sharing" }).click();
  await expect(page.getByRole("button", { name: "Pause sharing" })).toBeVisible();
});
