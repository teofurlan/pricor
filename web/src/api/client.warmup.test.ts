import { describe, expect, it, vi } from "vitest";
import { createApiClient } from "./client";

describe("warmUp in the api client", () => {
  it("POSTs to /warm-up", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ models: "ready" }), { status: 200 }));

    await createApiClient(fetchMock).warmUp();

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/warm-up");
    expect(init.method).toBe("POST");
  });

  it("swallows a network failure", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("offline"));

    await expect(createApiClient(fetchMock).warmUp()).resolves.toBeUndefined();
  });

  it("swallows an error response", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("boom", { status: 500 }));

    await expect(createApiClient(fetchMock).warmUp()).resolves.toBeUndefined();
  });
});
