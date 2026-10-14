import { describe, expect, it, vi } from "vitest";
import { createApiClient } from "./client";

const ok = () => new Response(JSON.stringify({ id: "s1" }), { status: 200, headers: { "Content-Type": "application/json" } });

describe("api client: exchange rates", () => {
  it("sends a typed rate for the run", async () => {
    const fetchMock = vi.fn().mockImplementation(async () => ok());
    const api = createApiClient(fetchMock);

    await api.setManualRate("s 1", "1420,50");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/imports/s%201/fx");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body)).toEqual({ rate: "1420,50" });
  });

  it("asks the server to fetch the rate again", async () => {
    const fetchMock = vi.fn().mockImplementation(async () => ok());
    const api = createApiClient(fetchMock);

    await api.refreshRate("s1");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/imports/s1/fx/refresh");
    expect(init.method).toBe("POST");
  });
});
