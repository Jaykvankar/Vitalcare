import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { BandBadge, SourceChip } from "../components/Monitor";
import { RecoveryCodes } from "../pages/Account";
import { initials } from "../components/Icons";
import Login from "../pages/Login";

describe("small components", () => {
  it("BandBadge uses plain-language labels", () => {
    render(<><BandBadge band="critical" /><BandBadge band="normal" /><BandBadge band={null} /></>);
    expect(screen.getByText("Critical")).toBeInTheDocument();
    expect(screen.getByText("Stable")).toBeInTheDocument();
    expect(screen.getByText("No data")).toBeInTheDocument();
  });

  it("SourceChip marks real data", () => {
    render(<SourceChip source="mimic:1" />);
    expect(screen.getByText("Real data replay")).toHaveClass("real");
  });

  it("initials drop titles", () => {
    expect(initials("Dr. Kiran Mehta")).toBe("KM");
    expect(initials("Asha")).toBe("A");
  });

  it("RecoveryCodes shows every code", () => {
    const done = vi.fn();
    render(<RecoveryCodes codes={["AAAAA-BBBBB", "CCCCC-DDDDD"]} onDone={done} />);
    expect(screen.getByText("AAAAA-BBBBB")).toBeInTheDocument();
    fireEvent.click(screen.getByText("I have saved them"));
    expect(done).toHaveBeenCalled();
  });
});

describe("Login", () => {
  it("asks for a TOTP code after the password and offers recovery codes", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({ mfa: "verify" }), { status: 200 }))));
    render(<MemoryRouter><Login /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "dr.mehta" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "secret-password" } });
    fireEvent.click(screen.getByText("Continue"));
    await waitFor(() => expect(screen.getByText("Two-step verification")).toBeInTheDocument());
    expect(screen.getByLabelText("Authentication code")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Lost your phone? Use a recovery code"));
    expect(screen.getByLabelText("Recovery code")).toBeInTheDocument();
    vi.unstubAllGlobals();
  });

  it("shows the server's error on a wrong password", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({ detail: "Invalid username or password" }), { status: 401 }))));
    render(<MemoryRouter><Login /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "x" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "y" } });
    fireEvent.click(screen.getByText("Continue"));
    expect(await screen.findByText("Invalid username or password")).toBeInTheDocument();
    vi.unstubAllGlobals();
  });
});
