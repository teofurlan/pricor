import { describe, expect, it, vi } from "vitest";
import { createApiClient } from "./client";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("api client: price report", () => {
  it("asks for the report with the threshold as a ratio", async () => {
    const fetchMock = vi.fn().mockImplementation(async () => jsonResponse({ import_id: "s2" }));
    const api = createApiClient(fetchMock);

    await api.report("s2");
    await api.report("s 2", "0.5");

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/imports/s2/report",
      "/imports/s%202/report?threshold=0.5",
    ]);
  });

  it("builds the CSV download link", () => {
    const api = createApiClient(vi.fn());

    expect(api.reportUrl("s2")).toBe("/imports/s2/report/export?format=csv");
    expect(api.reportUrl("s2", "0.25")).toBe("/imports/s2/report/export?format=csv&threshold=0.25");
  });

  it("reports a first import as a typed 409", async () => {
    const body = { error: { code: "no_previous_import", message: "nothing to compare with" } };
    const api = createApiClient(vi.fn().mockResolvedValue(jsonResponse(body, 409)));

    const failure = await api.report("s1").catch((error: unknown) => error);

    expect(failure).toMatchObject({ status: 409, code: "no_previous_import" });
  });
});
