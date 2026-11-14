import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Login from "../pages/Login";

const ACCOUNTS = [
  { username: "admin", role: "admin", full_name: "Asha Admin", password: "AmberFalconHarbor482" },
  { username: "dr.mehta", role: "clinician", full_name: "Dr. Kiran Mehta", password: "CedarOtterRiver735" },
  { username: "p.iyer", role: "patient", full_name: "Meera Iyer", password: "MapleHeronCanyon268" },
];

function mockServer(demo: boolean) {
  const logins: unknown[] = [];
  const json = (data: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(data), { status }));
  vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
    if (url === "/api/auth/demo-accounts") return json({ demo, accounts: demo ? ACCOUNTS : [] });
    if (url === "/api/auth/login") {
      logins.push(JSON.parse(String(init?.body)));
      return json({ detail: "Invalid username or password" }, 401);
    }
    return json({ detail: "not found" }, 404);
  }));
  return logins;
}

const passwordInput = () => document.querySelector<HTMLInputElement>('input[autocomplete="current-password"]')!;

describe("Login", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("demo role buttons fill the password but keep it hidden", async () => {
    mockServer(true);
    render(<MemoryRouter><Login /></MemoryRouter>);
    const roles = [
      [/Patient/, "p.iyer", "MapleHeronCanyon268"],
      [/Caretaker/, "dr.mehta", "CedarOtterRiver735"],
      [/Admin/, "admin", "AmberFalconHarbor482"],
    ] as const;
    for (const [name, username, password] of roles) {
      fireEvent.click((await screen.findAllByRole("button", { name }))[0]);
      expect(screen.getAllByDisplayValue(username).length).toBeGreaterThan(0);
      expect(passwordInput().value).toBe(password);
      expect(passwordInput().type).toBe("password");
      expect(screen.getByRole("button", { name: "Show password" })).toBeInTheDocument();
      expect(document.body.textContent).not.toContain(password);   // filled in, never displayed
    }
    await waitFor(() => expect(document.activeElement).toBe(passwordInput()));
  });

  it("shows no role buttons outside demo mode", async () => {
    mockServer(false);
    render(<MemoryRouter><Login /></MemoryRouter>);
    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/auth/demo-accounts", expect.anything()));
    expect(screen.queryByRole("button", { name: /Caretaker/ })).not.toBeInTheDocument();
  });

  it("can reveal the password and sends the username without surrounding spaces", async () => {
    const logins = mockServer(false);
    render(<MemoryRouter><Login /></MemoryRouter>);
    const user = document.querySelector<HTMLInputElement>('input[autocomplete="username"]')!;
    fireEvent.change(user, { target: { value: "  dr.mehta " } });
    fireEvent.change(passwordInput(), { target: { value: "AmberFalconHarbor482" } });
    expect(passwordInput().type).toBe("password");
    fireEvent.click(screen.getByRole("button", { name: "Show password" }));
    expect(passwordInput().type).toBe("text");
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByText("Invalid username or password")).toBeInTheDocument();
    expect(logins).toEqual([{ username: "dr.mehta", password: "AmberFalconHarbor482" }]);
  });
});
