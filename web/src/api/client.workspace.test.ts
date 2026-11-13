import { describe, expect, it, vi } from "vitest";
import { ApiError, createApiClient } from "./client";

describe("workspace in the api client", () => {
  it("asks GET /workspace for the personal link", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ link: "https://x.test/w/abc" }), { status: 200 }));
    const api = createApiClient(fetchMock);

    expect(await api.workspace()).toEqual({ link: "https://x.test/w/abc" });
    expect(fetchMock.mock.calls[0][0]).toBe("/workspace");
  });

  it("surfaces workspace_required as an ApiError", async () => {
    const body = { error: { code: "workspace_required", message: "open a workspace" } };
    const api = createApiClient(vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status: 401 })));

    await expect(api.listSheets(new File(["x"], "a.xlsx"))).rejects.toMatchObject({ status: 401, code: "workspace_required" });
    await expect(api.listSheets(new File(["x"], "a.xlsx"))).rejects.toBeInstanceOf(ApiError);
  });
});
