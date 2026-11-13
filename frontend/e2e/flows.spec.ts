import { expect, test } from "@playwright/test";
import { login, logout } from "./helpers";

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

test("clinician on the care team can issue a one-time pairing code", async ({ page }) => {
  await login(page, "dr.mehta");
  await page.locator("table tbody tr").first().click();
  await page.getByRole("button", { name: "Pair device" }).click();
  await page.getByRole("button", { name: "Create pairing code" }).click();
  const code = (await page.getByLabel("Pairing code").textContent())!.trim();
  expect(code).toMatch(/^[A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4}$/);
  await expect(page.getByText(/Expires in/)).toBeVisible();
  await page.getByRole("button", { name: "Close" }).click();
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
