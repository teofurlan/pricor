import { describe, expect, it, vi } from "vitest";
import { createApiClient } from "./client";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("memory API client", () => {
  it("lists memories", async () => {
    const memories = [{ id: "m1", text: "VAT is included", supplier_name: "Acme", source: "note", created_at: "2026-10-18T10:00:00Z", updated_at: "2026-10-18T10:00:00Z" }];
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(memories));

    await expect(createApiClient(fetchMock).listMemories()).resolves.toEqual(memories);
    expect(fetchMock).toHaveBeenCalledWith("/memories", undefined);
  });

  it("creates notes and accepted suggestions with their distinct payloads", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse({ id: "m1" }, 201)));
    const api = createApiClient(fetchMock);

    await api.createMemoryNote("VAT is included", "Acme");
    await api.rememberSuggestion("session one", "vat question");

    expect(fetchMock.mock.calls.map(([url, init]) => [url, init.method, init.body])).toEqual([
      ["/memories", "POST", JSON.stringify({ text: "VAT is included", supplier_name: "Acme" })],
      ["/memories", "POST", JSON.stringify({ session_id: "session one", question_id: "vat question" })],
    ]);
  });

  it("edits and deletes a memory using an encoded id", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ id: "m 1", text: "Updated" }))
      .mockResolvedValueOnce(jsonResponse(null, 204));
    const api = createApiClient(fetchMock);

    await api.editMemory("m 1", "Updated");
    await api.deleteMemory("m 1");

    expect(fetchMock.mock.calls.map(([url, init]) => [url, init.method, init.body])).toEqual([
      ["/memories/m%201", "PATCH", JSON.stringify({ text: "Updated" })],
      ["/memories/m%201", "DELETE", undefined],
    ]);
  });
});
