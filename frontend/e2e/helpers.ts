import { createHmac } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { Page, expect } from "@playwright/test";

const CREDS = resolve(process.cwd(), "../.e2e/credentials.txt");

export function credentials(username: string): { password: string; totp?: string } {
  const lines = readFileSync(CREDS, "utf8").split(/\r?\n/);
  const start = lines.findIndex((l) => l.startsWith(`== ${username} (`));
  if (start < 0) throw new Error(`no seeded credentials for ${username}`);
  const end = lines.findIndex((l, i) => i > start && !l.trim());
  const block = lines.slice(start + 1, end < 0 ? undefined : end);
  const value = (label: string) => {
    const i = block.indexOf(`${label}:`);
    return i >= 0 ? block[i + 1]?.trim() : undefined;
  };
  const password = value("password");
  if (!password) throw new Error(`no password for ${username}`);
  return { password, totp: value("totp secret") };
}

function base32(s: string): Buffer {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const c of s.replace(/=+$/, "")) bits += alphabet.indexOf(c).toString(2).padStart(5, "0");
  const bytes = bits.match(/.{8}/g)!.map((b) => parseInt(b, 2));
  return Buffer.from(bytes);
}

/** RFC 6238 TOTP with HMAC-SHA-512, 6 digits, 30 s (same parameters as the server). */
export function totpNow(secret: string, offsetSteps = 0): string {
  const step = Math.floor(Date.now() / 1000 / 30) + offsetSteps;
  const msg = Buffer.alloc(8);
  msg.writeBigUInt64BE(BigInt(step));
  const h = createHmac("sha512", base32(secret)).update(msg).digest();
  const o = h[h.length - 1] & 0xf;
  const n = ((h[o] & 0x7f) << 24) | (h[o + 1] << 16) | (h[o + 2] << 8) | h[o + 3];
  return String(n % 1_000_000).padStart(6, "0");
}

let lastStep = 0;

export async function login(page: Page, username: string) {
  const { password, totp } = credentials(username);
  await page.goto("/");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Continue" }).click();
  if (totp) {
    // The server rejects a reused code, so wait for a fresh 30 s step if this one was already used.
    let step = Math.floor(Date.now() / 1000 / 30);
    while (step <= lastStep) {
      await page.waitForTimeout(1000);
      step = Math.floor(Date.now() / 1000 / 30);
    }
    lastStep = step;
    await page.getByLabel("Authentication code").fill(totpNow(totp));
    await page.getByRole("button", { name: "Verify and sign in" }).click();
  }
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
}

export async function logout(page: Page) {
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
}
