import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { connectionOf, pairingLink } from "../api";
import { ConnectDevice } from "../components/ConnectDevice";
import { resetCatalogCacheForTests } from "../hooks";

const NOW = Date.parse("2026-11-13T10:00:00Z");
const ago = (s: number) => new Date(NOW - s * 1000).toISOString();

describe("connectionOf", () => {
  it("turns the last reading time into a plain status", () => {
    expect(connectionOf({ active: false, last_seen: ago(5) }, NOW)).toBe("revoked");
    expect(connectionOf({ active: true, last_seen: null }, NOW)).toBe("never");
    expect(connectionOf({ active: true, last_seen: ago(120) }, NOW)).toBe("receiving");
    expect(connectionOf({ active: true, last_seen: ago(121) }, NOW)).toBe("recent");
    expect(connectionOf({ active: true, last_seen: ago(600) }, NOW)).toBe("recent");
    expect(connectionOf({ active: true, last_seen: ago(601) }, NOW)).toBe("quiet");
  });
});

describe("pairingLink", () => {
  it("encodes server, id and code so device_client --link can read them", () => {
    const link = pairingLink("https://vitalcare.example.org", "7f3c0a1b", "K7QM-2WXR-9HPD");
    expect(link).toBe("vitalcare-pair:v1?server=https%3A%2F%2Fvitalcare.example.org&id=7f3c0a1b&code=K7QM-2WXR-9HPD");
  });
});

const CATALOG = [
  {
    id: "gateway_kit", name: "Vitalcare gateway", icon: "Watch", measures: ["Heart rate", "SpO₂"],
    connects_through: "A small computer next to the patient", status: "ready", admin_only: false,
    default_label: "Home monitoring gateway", what_you_need: ["A gateway"], how_to_connect: ["Scan the QR code."],
    patient_tips: [],
  },
  {
    id: "bp_cuff", name: "Blood-pressure cuff", icon: "Gauge", measures: ["Blood pressure"],
    connects_through: "Bluetooth to the gateway", status: "needs_adapter", admin_only: false,
    default_label: "Blood-pressure cuff", what_you_need: ["A cuff"], how_to_connect: ["Scan the QR code."], patient_tips: [],
  },
  {
    id: "simulator", name: "Built-in test monitor", icon: "Play", measures: [], connects_through: "inside",
    status: "ready", admin_only: true, default_label: "Test monitor", what_you_need: [], how_to_connect: [], patient_tips: [],
  },
];

function mockServer() {
  const state = { codeStatus: "waiting", lastSeen: null as string | null, body: null as unknown };
  const json = (data: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(data), { status }));
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    if (url === "/api/devices/catalog") return json(CATALOG);
    if (url === "/api/devices/pairing-codes" && init?.method === "POST") {
      state.body = JSON.parse(String(init.body));
      return json({ pairing_id: "ab12cd34", code: "K7QM-2WXR-9HPD", expires_at: new Date(Date.now() + 600_000).toISOString() });
    }
    if (url === "/api/devices/pairing-codes/ab12cd34") {
      return json({ status: state.codeStatus, device_id: state.codeStatus === "paired" ? "dev-1" : null });
    }
    if (url.startsWith("/api/devices?patient_id=7")) return json([{ id: "dev-1", label: "x", active: true, last_seen: state.lastSeen }]);
    return json({ detail: "not found" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  return state;
}

describe("ConnectDevice wizard", () => {
  beforeEach(() => resetCatalogCacheForTests());
  afterEach(() => vi.unstubAllGlobals());

  it("guides from choosing a device to readings arriving", async () => {
    const server = mockServer();
    render(<MemoryRouter><ConnectDevice patientId={7} patientName="Kavita Verma" onClose={() => {}} /></MemoryRouter>);

    // Step 1: catalog cards, admin-only test monitor hidden for non-admins
    expect(await screen.findByText("Vitalcare gateway")).toBeInTheDocument();
    expect(screen.getByText("Needs gateway adapter")).toBeInTheDocument();
    expect(screen.queryByText("Built-in test monitor")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Vitalcare gateway"));

    // Step 2: name it
    const name = screen.getByLabelText("Name shown in the device list") as HTMLInputElement;
    expect(name.value).toBe("Home monitoring gateway");
    fireEvent.change(name, { target: { value: "Kavita's gateway" } });
    fireEvent.click(screen.getByText("Create connection code"));

    // Step 3: code + QR + IT command
    expect(await screen.findByText("K7QM-2WXR-9HPD")).toBeInTheDocument();
    expect(screen.getByLabelText("Pairing QR code").querySelector("svg")).not.toBeNull();
    expect(server.body).toEqual({ patient_id: 7, label: "Kavita's gateway", device_type: "gateway_kit" });
    expect(screen.getByText(/device_client.py pair --link "vitalcare-pair:v1\?server=/)).toBeInTheDocument();

    // Step 4: the device uses the code, then the first reading arrives
    server.codeStatus = "paired";
    expect(await screen.findByText("Connected.", {}, { timeout: 6000 })).toBeInTheDocument();
    server.lastSeen = new Date().toISOString();
    expect(await screen.findByText("Readings are arriving.", {}, { timeout: 6000 })).toBeInTheDocument();
  }, 15000);

  it("offers a new code when the old one expired", async () => {
    const server = mockServer();
    render(<MemoryRouter><ConnectDevice patientId={7} patientName="P" onClose={() => {}} /></MemoryRouter>);
    fireEvent.click(await screen.findByText("Blood-pressure cuff"));
    fireEvent.click(screen.getByText("Create connection code"));
    await screen.findByText("K7QM-2WXR-9HPD");
    server.codeStatus = "expired";
    await waitFor(() => expect(screen.getByText(/This code has expired/)).toBeInTheDocument(), { timeout: 6000 });
    expect(screen.getByText("Create a new code")).toBeInTheDocument();
  }, 15000);
});
