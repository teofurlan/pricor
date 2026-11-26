import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, type ApiClient, type WorkspaceApiClient } from "../api/client";
import { ServerConfigProvider } from "../api/serverConfig";
import type { ServerConfig } from "../api/types";
import { renderWithI18n } from "../test/render";
import { ImportWizard } from "./ImportWizard";

const LINK = "https://pricor.test/#w=AbCdEf";

function api(config: ServerConfig, overrides: Record<string, unknown> = {}) {
  return {
    listSheets: vi.fn().mockResolvedValue([]),
    config: vi.fn().mockResolvedValue(config),
    workspace: vi.fn().mockResolvedValue({ link: LINK }),
    ...overrides,
  } as unknown as ApiClient & WorkspaceApiClient;
}

function mount(client: ApiClient, language: "en" | "es" = "en") {
  return renderWithI18n(<ServerConfigProvider api={client}><ImportWizard api={client} /></ServerConfigProvider>, language);
}

afterEach(() => vi.restoreAllMocks());

describe("private workspace panel", () => {
  it("establishes the workspace cookie silently without showing a raw personal link when Google auth is off", async () => {
    const client = api({ model_provider: "gemini", demo: true, workspaces: true });
    mount(client);

    await waitFor(() => expect(client.workspace).toHaveBeenCalledTimes(1));
    expect(screen.queryByDisplayValue(LINK)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Copy link" })).not.toBeInTheDocument();
  });

  it("shows the Google sign-in strip in Spanish (usted) when google_client_id is configured", async () => {
    mount(api({ model_provider: "gemini", demo: true, workspaces: true, google_client_id: "g-123" }), "es");

    expect(await screen.findByRole("button", { name: "Continuar con Google" })).toBeInTheDocument();
    expect(screen.getByText(/sus proveedores y formatos se guardan en este navegador/i)).toBeInTheDocument();
    expect(screen.queryByDisplayValue(LINK)).not.toBeInTheDocument();
  });

  it.each([[false], [undefined]])("is hidden and never calls /workspace when workspaces is %s", async (workspaces) => {
    const client = api({ model_provider: "gemini", demo: true, ...(workspaces === undefined ? {} : { workspaces }) });
    mount(client);

    await screen.findByLabelText("Price list file");
    await waitFor(() => expect(client.config).toHaveBeenCalled());
    expect(screen.queryByRole("region", { name: "Your private space" })).not.toBeInTheDocument();
    expect(client.workspace).not.toHaveBeenCalled();
  });

  it("does not load memories or the output format before the workspace cookie exists", async () => {
    let release: (value: { link: string }) => void = () => {};
    const order: string[] = [];
    const client = api({ model_provider: "gemini", demo: true, workspaces: true }, {
      workspace: vi.fn(() => new Promise((resolve) => { release = resolve; order.push("workspace"); })),
      listMemories: vi.fn(() => { order.push("memories"); return Promise.resolve([]); }),
      getOutputFormat: vi.fn(() => { order.push("format"); return Promise.resolve(null); }),
    });
    mount(client);

    await waitFor(() => expect(order).toEqual(["workspace"]));
    await act(async () => release({ link: LINK }));
    await waitFor(() => expect(order).toContain("memories"));
    expect(order[0]).toBe("workspace");
  });

  it("does not load saved suppliers before the workspace cookie exists and passes them to UploadForm after settling", async () => {
    let release: (value: { link: string }) => void = () => { };
    const order: string[] = [];
    const client = api({ model_provider: "gemini", demo: true, workspaces: true }, {
      workspace: vi.fn(() => new Promise((resolve) => { release = resolve; order.push("workspace"); })),
      listSuppliers: vi.fn(() => { order.push("suppliers"); return Promise.resolve(["Ferretería Norte"]); }),
    });
    mount(client);

    await waitFor(() => expect(order).toEqual(["workspace"]));
    await act(async () => release({ link: LINK }));
    await waitFor(() => expect(order).toEqual(["workspace", "suppliers"]));

    const file = new File(["x"], "a.csv", { type: "text/csv" });
    await userEvent.upload(document.querySelector("input[type=file]") as HTMLInputElement, file);
    const input = await screen.findByLabelText("Supplier for a.csv");
    await userEvent.click(input);
    expect(await screen.findByRole("option", { name: /Ferretería Norte/ })).toBeInTheDocument();
  });

  it("tells the user to reload on workspace_required", async () => {
    const client = api({ model_provider: "gemini", demo: true, workspaces: false }, {
      listSheets: vi.fn().mockRejectedValue(new ApiError(401, "workspace_required", "open a workspace")),
    });
    mount(client);
    expect(await screen.findByLabelText("Price list file")).toBeInTheDocument();
    // Drive the error through createImport, which the wizard surfaces in the banner.
    (client as unknown as { createImport: unknown }).createImport = vi.fn().mockRejectedValue(new ApiError(401, "workspace_required", "x"));
    const file = new File(["x"], "a.csv", { type: "text/csv" });
    await userEvent.upload(document.querySelector("input[type=file]") as HTMLInputElement, file);
    await userEvent.click(await screen.findByRole("button", { name: "Start import" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/reload the page/i);
  });
});
