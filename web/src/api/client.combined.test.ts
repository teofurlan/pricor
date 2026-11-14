import { describe, expect, it, vi } from "vitest";
import { createApiClient } from "./client";

describe("combined export in the api client", () => {
  it("posts the session ids in order and returns the file with its name", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response("a,b", { status: 200, headers: { "Content-Disposition": 'attachment; filename="pricor-combined-2-files-products.csv"' } }),
    );
    const api = createApiClient(fetchMock);

    const result = await api.downloadCombined(["s1", "s2"], "csv", "products");

    expect(fetchMock.mock.calls[0][0]).toBe("/imports/combined-export");
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: "POST" });
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ session_ids: ["s1", "s2"], format: "csv", kind: "products" });
    expect(result.fileName).toBe("pricor-combined-2-files-products.csv");
    expect(result.blob.size).toBe(3);
  });

  it("reports the server's refusal", async () => {
    const body = { error: { code: "invalid_operation", message: "different output formats" } };
    const api = createApiClient(vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status: 409 })));
    await expect(api.downloadCombined(["s1"], "xlsx", "products")).rejects.toMatchObject({ status: 409, code: "invalid_operation" });
  });
});
