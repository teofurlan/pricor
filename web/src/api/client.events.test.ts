import { describe, expect, it, vi } from "vitest";
import { createApiClient } from "./client";

describe("recordEvent in the api client", () => {
  it("POSTs the event and the group as JSON to /events", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));

    await createApiClient(fetchMock).recordEvent("approved", "grupo-1");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/events");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ event: "approved", group: "grupo-1" });
  });

  it("sends null when there is no group", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));

    await createApiClient(fetchMock).recordEvent("visit", null);

    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ event: "visit", group: null });
  });
});
