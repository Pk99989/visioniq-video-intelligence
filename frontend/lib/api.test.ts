/** Frontend unit tests (Phase 8): lib/api.ts — error stringification,
 *  auth header, pagination helper.
 *
 *  Run: npm test (from frontend/)
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, apiPage } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

function mockFetch(body: unknown, { status = 200, headers = {} }: {
  status?: number; headers?: Record<string, string>;
} = {}) {
  const h = new Headers(headers);
  vi.stubGlobal("fetch", vi.fn(async () => ({
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 404 ? "Not Found" : "OK",
    headers: h,
    json: async () => body,
  })));
  return fetch as unknown as ReturnType<typeof vi.fn>;
}

describe("api", () => {
  it("sends the stored token as a Bearer header", async () => {
    localStorage.setItem("visioniq_token", "tok-1");
    const fetchMock = mockFetch({ ok: true });
    await api("/api/v1/videos");
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/videos"),
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: "Bearer tok-1" }),
      }),
    );
  });

  it("stringifies a FastAPI 422 detail list instead of throwing an object", async () => {
    mockFetch({ detail: [{ loc: ["body", "query"], msg: "field required" }] }, { status: 422 });
    await expect(api("/api/v1/search", { method: "POST", body: "{}" }))
      .rejects.toThrow("422: body.query: field required");
  });

  it("passes a plain string detail through", async () => {
    mockFetch({ detail: "Video not found" }, { status: 404 });
    await expect(api("/api/v1/videos/99")).rejects.toThrow("404: Video not found");
  });

  it("returns undefined for 204 No Content", async () => {
    mockFetch(null, { status: 204 });
    await expect(api("/api/v1/videos/1", { method: "DELETE" })).resolves.toBeUndefined();
  });
});

describe("apiPage", () => {
  it("returns items plus the X-Total-Count header", async () => {
    mockFetch([{ id: 1 }, { id: 2 }], { headers: { "x-total-count": "7" } });
    await expect(apiPage("/api/v1/videos?limit=2&offset=0"))
      .resolves.toEqual({ items: [{ id: 1 }, { id: 2 }], total: 7 });
  });

  it("falls back to the page length when the header is missing", async () => {
    mockFetch([{ id: 1 }]);
    await expect(apiPage("/api/v1/videos")).resolves.toEqual({ items: [{ id: 1 }], total: 1 });
  });
});
