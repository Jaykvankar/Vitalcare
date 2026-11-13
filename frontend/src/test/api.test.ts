import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, sourceInfo, timeAgo } from "../api";

describe("sourceInfo", () => {
  it("labels real-data replays and synthetic data honestly", () => {
    expect(sourceInfo("mimic:249805")).toMatchObject({ kind: "real", label: "Real data replay" });
    expect(sourceInfo("bidmc:7").detail).toContain("BP/temp not recorded");
    expect(sourceInfo("eicu:141765")).toMatchObject({ kind: "real", detail: expect.stringContaining("eICU") });
    expect(sourceInfo("synthetic").kind).toBe("synthetic");
    expect(sourceInfo(undefined).kind).toBe("none");
  });
});

describe("timeAgo", () => {
  it("formats relative times", () => {
    expect(timeAgo(null)).toBe("never");
    expect(timeAgo(new Date(Date.now() - 5_000).toISOString())).toMatch(/s ago$/);
    expect(timeAgo(new Date(Date.now() - 3 * 3600_000).toISOString())).toBe("3 h ago");
  });
});

describe("api()", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("sends the CSRF header and JSON body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await api("/api/x", { method: "POST", body: { a: 1 } });
    const [, init] = fetchMock.mock.calls[0];
    expect(init.headers["X-RPM-Request"]).toBe("1");
    expect(init.headers["Content-Type"]).toBe("application/json");
    expect(init.body).toBe('{"a":1}');
    expect(init.credentials).toBe("same-origin");
  });

  it("turns error responses into ApiError with the server's message", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "Nope" }), { status: 403 })));
    await expect(api("/api/x")).rejects.toMatchObject({ status: 403, message: "Nope" });
    await expect(api("/api/x")).rejects.toBeInstanceOf(ApiError);
  });
});
