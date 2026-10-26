import { describe, expect, it, vi } from "vitest";
import { ApiError, createApiClient } from "./client";

const listing = {
  id: "demo-1",
  file_name: "demo-semana-1.xlsx",
  supplier_name: "Distribuidora Ejemplo",
  week: 1,
  title: { en: "Week 1", es: "Semana 1" },
  description: { en: "First list", es: "Primera lista" },
};

describe("sample lists in the api client", () => {
  it("lists the samples", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify([listing]), { status: 200 }));
    const api = createApiClient(fetchMock);

    expect(await api.listSamples()).toEqual([listing]);
    expect(fetchMock.mock.calls[0][0]).toBe("/samples");
  });

  it("downloads a sample as a File with its own name and type", async () => {
    const type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
    const fetchMock = vi.fn().mockResolvedValue(new Response("abc", { status: 200, headers: { "Content-Type": type } }));
    const api = createApiClient(fetchMock);

    const file = await api.downloadSample(listing);

    expect(fetchMock.mock.calls[0][0]).toBe("/samples/demo-1");
    expect(file.name).toBe("demo-semana-1.xlsx");
    expect(file.type).toBe(type);
    expect(file.size).toBe(3);
  });

  it("reports a missing sample with the server's error", async () => {
    const body = { error: { code: "sample_not_found", message: "no sample list" } };
    const api = createApiClient(vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status: 404 })));

    await expect(api.downloadSample(listing)).rejects.toMatchObject({ status: 404, code: "sample_not_found" });
    await expect(api.downloadSample(listing)).rejects.toBeInstanceOf(ApiError);
  });
});
