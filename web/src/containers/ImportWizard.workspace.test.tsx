import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, type ApiClient, type WorkspaceApiClient } from "../api/client";
import { ServerConfigProvider } from "../api/serverConfig";
import type { ServerConfig } from "../api/types";
import { renderWithI18n } from "../test/render";
import { ImportWizard } from "./ImportWizard";

const LINK = "https://pricor.test/w/AbCdEf";

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
  it("shows the personal link once when workspaces is on", async () => {
    const client = api({ model_provider: "gemini", demo: true, workspaces: true });
    mount(client);

    expect(await screen.findByText("Your private space")).toBeInTheDocument();
    expect(screen.getByDisplayValue(LINK)).toBeInTheDocument();
    expect(screen.getByText(/anyone with the link can see your lists/i)).toBeInTheDocument();
    expect(client.workspace).toHaveBeenCalledTimes(1);
  });

  it("is in Spanish with the usted register", async () => {
    mount(api({ model_provider: "gemini", demo: true, workspaces: true }), "es");

    expect(await screen.findByText("Su espacio privado")).toBeInTheDocument();
    expect(screen.getByText(/guarde este enlace para volver desde otra computadora o celular; quien tenga el enlace puede ver sus listas/i)).toBeInTheDocument();
  });

  it.each([[false], [undefined]])("is hidden and never calls /workspace when workspaces is %s", async (workspaces) => {
    const client = api({ model_provider: "gemini", demo: true, ...(workspaces === undefined ? {} : { workspaces }) });
    mount(client);

    await screen.findByLabelText("Supplier name");
    await waitFor(() => expect(client.config).toHaveBeenCalled());
    expect(screen.queryByText("Your private space")).not.toBeInTheDocument();
    expect(client.workspace).not.toHaveBeenCalled();
  });

  it("copies the link and confirms", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    mount(api({ model_provider: "gemini", demo: true, workspaces: true }));

    await userEvent.click(await screen.findByRole("button", { name: "Copy link" }));

    expect(writeText).toHaveBeenCalledWith(LINK);
    expect(await screen.findByText("Copied")).toBeInTheDocument();
    vi.unstubAllGlobals();
  });

  it("keeps the link selectable and says so when copying fails", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("denied"));
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    mount(api({ model_provider: "gemini", demo: true, workspaces: true }));

    await userEvent.click(await screen.findByRole("button", { name: "Copy link" }));

    expect(await screen.findByText("Could not copy. Select the link and copy it by hand.")).toBeInTheDocument();
    expect(screen.queryByText("Copied")).not.toBeInTheDocument();
    expect(screen.getByDisplayValue(LINK)).toBeInTheDocument();
    vi.unstubAllGlobals();
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

  it("tells the user to reload on workspace_required", async () => {
    const client = api({ model_provider: "gemini", demo: true, workspaces: false }, {
      listSheets: vi.fn().mockRejectedValue(new ApiError(401, "workspace_required", "open a workspace")),
    });
    mount(client);
    expect(await screen.findByLabelText("Supplier name")).toBeInTheDocument();
    // Drive the error through createImport, which the wizard surfaces in the banner.
    (client as unknown as { createImport: unknown }).createImport = vi.fn().mockRejectedValue(new ApiError(401, "workspace_required", "x"));
    const file = new File(["x"], "a.csv", { type: "text/csv" });
    await userEvent.type(screen.getByLabelText("Supplier name"), "Acme");
    await userEvent.upload(document.querySelector("input[type=file]") as HTMLInputElement, file);
    await userEvent.click(await screen.findByRole("button", { name: "Start import" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/reload the page/i);
  });
});
