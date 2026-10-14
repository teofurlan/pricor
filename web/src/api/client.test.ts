import { describe, expect, it, vi } from "vitest";
import { ApiError, createApiClient } from "./client";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("api client", () => {
  it("uploads the file as multipart form data", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ id: "s1" }, 201));
    const api = createApiClient(fetchMock);
    const file = new File(["a,b"], "lista.csv", { type: "text/csv" });

    await api.createImport({ file, supplierName: "Acme", sheet: "Hoja1", language: "es" });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/imports");
    expect(init.method).toBe("POST");
    const form = init.body as FormData;
    expect(form.get("supplier_name")).toBe("Acme");
    expect(form.get("sheet")).toBe("Hoja1");
    expect(form.get("language")).toBe("es");
    expect((form.get("file") as File).name).toBe("lista.csv");
  });

  it("leaves the sheet out when it is blank", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ id: "s1" }, 201));
    const api = createApiClient(fetchMock);
    const file = new File(["a"], "a.csv");
    await api.createImport({ file, supplierName: "Acme", sheet: "  ", language: "en" });
    expect((fetchMock.mock.calls[0][1].body as FormData).has("sheet")).toBe(false);
  });

  it("asks for a fresh import only when told to", async () => {
    const fetchMock = vi.fn().mockImplementation(async () => jsonResponse({ id: "s1" }, 201));
    const api = createApiClient(fetchMock);
    const file = new File(["a"], "a.csv");

    await api.createImport({ file, supplierName: "Acme", language: "en" });
    await api.createImport({ file, supplierName: "Acme", language: "en", forceFirstImport: true });

    const forms = fetchMock.mock.calls.map(([, init]) => init.body as FormData);
    expect(forms[0].has("force_first_import")).toBe(false);
    expect(forms[1].get("force_first_import")).toBe("true");
  });

  it("sends header, roles and answers as JSON", async () => {
    const fetchMock = vi.fn().mockImplementation(async () => jsonResponse({ id: "s1" }));
    const api = createApiClient(fetchMock);

    await api.chooseHeader("s1", null);
    await api.setRoles("s1", { 2: "cost_price" });
    await api.answer("s1", "currency", "ARS");

    const calls = fetchMock.mock.calls.map(([url, init]) => [url, init.method, init.body]);
    expect(calls).toEqual([
      ["/imports/s1/header", "PUT", JSON.stringify({ row_index: null })],
      ["/imports/s1/roles", "PUT", JSON.stringify({ roles: { 2: "cost_price" } })],
      ["/imports/s1/answers", "POST", JSON.stringify({ question_id: "currency", option: "ARS" })],
    ]);
  });

  it("requests a preview page with offset and limit", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ items: [] }));
    await createApiClient(fetchMock).preview("s1", 50, 25);
    expect(fetchMock.mock.calls[0][0]).toBe("/imports/s1/preview?offset=50&limit=25");
  });

  it("builds download links for both formats", () => {
    const api = createApiClient(vi.fn());
    expect(api.exportUrl("s 1", "xlsx")).toBe("/imports/s%201/export?format=xlsx");
    expect(api.rejectedUrl("s1", "csv")).toBe("/imports/s1/rejected?format=csv");
  });

  it("turns the error envelope into an ApiError", async () => {
    const body = { error: { code: "no_accepted_rows", message: "nothing to approve" } };
    const api = createApiClient(vi.fn().mockResolvedValue(jsonResponse(body, 409)));

    const failure = await api.approve("s1").catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(ApiError);
    expect(failure).toMatchObject({ status: 409, code: "no_accepted_rows", message: "nothing to approve" });
  });

  it("reports a non-JSON failure as an unexpected error with its status", async () => {
    const html = new Response("<html>bad gateway</html>", { status: 502 });
    const failure = await createApiClient(vi.fn().mockResolvedValue(html))
      .getImport("s1")
      .catch((error: unknown) => error);
    expect(failure).toMatchObject({ status: 502, code: "unexpected_response" });
  });

  it("reports an unreachable server as a network error", async () => {
    const api = createApiClient(vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const failure = await api.getImport("s1").catch((error: unknown) => error);
    expect(failure).toMatchObject({ status: 0, code: "network_error" });
  });
});
