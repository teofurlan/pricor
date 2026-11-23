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

  it("lists sheets for an uploaded workbook file", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ sheets: ["Hoja 1", "Hoja 2"] }));
    const api = createApiClient(fetchMock);
    const file = new File(["dummy"], "catalogo.xlsx");

    const sheets = await api.listSheets(file);

    expect(sheets).toEqual(["Hoja 1", "Hoja 2"]);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/sheets");
    expect(init.method).toBe("POST");
    const form = init.body as FormData;
    expect((form.get("file") as File).name).toBe("catalogo.xlsx");
  });

  it("requests a preview page with offset and limit", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ items: [] }));
    await createApiClient(fetchMock).preview("s1", 50, 25);
    expect(fetchMock.mock.calls[0][0]).toBe("/imports/s1/preview?offset=50&limit=25");
  });

  it("includes q and status query params when preview filters are active", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse({ items: [] })));
    const client = createApiClient(fetchMock);
    await client.preview("s1", 0, 50, { query: "  lámpara  ", status: "rejected" });
    expect(fetchMock.mock.calls[0][0]).toBe("/imports/s1/preview?offset=0&limit=50&q=l%C3%A1mpara&status=rejected");

    await client.preview("s1", 0, 50, { query: "   ", status: "all" });
    expect(fetchMock.mock.calls[1][0]).toBe("/imports/s1/preview?offset=0&limit=50");
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

  it("fetches server config from GET /config", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ model_provider: "gemini", demo: false }));
    const api = createApiClient(fetchMock);
    const cfg = await api.config();
    expect(cfg).toEqual({ model_provider: "gemini", demo: false });
    expect(fetchMock).toHaveBeenCalledWith("/config", undefined);
  });

  it("signs in with Google via POST /workspace/google and unlinks via DELETE /workspace/google", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ status: "linked", link: "https://pricor.test/#w=abc", account: { email: "ana@example.com" } }))
      .mockResolvedValueOnce(jsonResponse({ status: "switched", link: "https://pricor.test/#w=xyz", account: { email: "ana@example.com" } }))
      .mockResolvedValueOnce(jsonResponse({ link: "https://pricor.test/#w=xyz", account: null }));
    const api = createApiClient(fetchMock);

    const linked = await api.googleSignIn!("id-token-1");
    expect(linked).toEqual({ status: "linked", link: "https://pricor.test/#w=abc", account: { email: "ana@example.com" } });

    const switched = await api.googleSignIn!("id-token-2", "use_account");
    expect(switched).toEqual({ status: "switched", link: "https://pricor.test/#w=xyz", account: { email: "ana@example.com" } });

    const unlinked = await api.unlinkGoogleAccount!();
    expect(unlinked).toEqual({ link: "https://pricor.test/#w=xyz", account: null });

    expect(fetchMock.mock.calls).toEqual([
      ["/workspace/google", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ credential: "id-token-1", resolution: "auto" }) }],
      ["/workspace/google", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ credential: "id-token-2", resolution: "use_account" }) }],
      ["/workspace/google", { method: "DELETE" }],
    ]);
  });
});
