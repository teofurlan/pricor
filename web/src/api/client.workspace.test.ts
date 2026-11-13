import { describe, expect, it, vi } from "vitest";
import { ApiError, createApiClient } from "./client";

describe("workspace in the api client", () => {
  it("asks GET /workspace for the personal link", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ link: "https://x.test/#w=abc" }), { status: 200 }));
    const api = createApiClient(fetchMock);

    expect(await api.workspace()).toEqual({ link: "https://x.test/#w=abc" });
    expect(fetchMock.mock.calls[0][0]).toBe("/workspace");
  });

  it("surfaces workspace_required as an ApiError", async () => {
    const body = { error: { code: "workspace_required", message: "open a workspace" } };
    const api = createApiClient(vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status: 401 })));

    await expect(api.listSheets(new File(["x"], "a.xlsx"))).rejects.toMatchObject({ status: 401, code: "workspace_required" });
    await expect(api.listSheets(new File(["x"], "a.xlsx"))).rejects.toBeInstanceOf(ApiError);
  });

  it("claims a token with a JSON POST and returns the link", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ link: "https://x.test/#w=abc" }), { status: 200 }));
    const api = createApiClient(fetchMock);

    expect(await api.claimWorkspace("abc")).toEqual({ link: "https://x.test/#w=abc" });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/workspace/claim");
    expect(init.method).toBe("POST");
    expect(init.headers).toMatchObject({ "Content-Type": "application/json" });
    expect(JSON.parse(init.body)).toEqual({ token: "abc" });
  });

  it("surfaces workspace_not_found when the claim is refused", async () => {
    const body = { error: { code: "workspace_not_found", message: "no such workspace" } };
    const api = createApiClient(vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status: 404 })));

    await expect(api.claimWorkspace("abc")).rejects.toMatchObject({ status: 404, code: "workspace_not_found" });
  });

  it("asks GET /workspace/current and returns the link", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ link: "https://x.test/#w=abc" }), { status: 200 }));
    const api = createApiClient(fetchMock);

    expect(await api.currentWorkspace()).toEqual({ link: "https://x.test/#w=abc" });
    expect(fetchMock.mock.calls[0][0]).toBe("/workspace/current");
  });

  it("returns null from /workspace/current when there is no workspace yet", async () => {
    const body = { error: { code: "workspace_not_found", message: "none" } };
    const api = createApiClient(vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status: 404 })));

    expect(await api.currentWorkspace()).toBeNull();
  });

  it("does not hide other failures of /workspace/current", async () => {
    const api = createApiClient(vi.fn().mockResolvedValue(new Response("boom", { status: 500 })));

    await expect(api.currentWorkspace()).rejects.toMatchObject({ status: 500 });
  });
});
