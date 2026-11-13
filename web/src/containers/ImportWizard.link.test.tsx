import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, type ApiClient, type MemoryApiClient, type WorkspaceApiClient } from "../api/client";
import { ServerConfigProvider } from "../api/serverConfig";
import type { ServerConfig } from "../api/types";
import { renderWithI18n } from "../test/render";
import { ImportWizard } from "./ImportWizard";

const TOKEN = "A".repeat(43);
const OTHER = "B".repeat(43);
const CONFIG: ServerConfig = { model_provider: "gemini", demo: true, workspaces: true };
const link = (token: string) => `https://pricor.test/#w=${token}`;

function api(config: ServerConfig, overrides: Record<string, unknown> = {}) {
  return {
    listSheets: vi.fn().mockResolvedValue([]),
    config: vi.fn().mockResolvedValue(config),
    workspace: vi.fn().mockResolvedValue({ link: link(OTHER) }),
    currentWorkspace: vi.fn().mockResolvedValue(null),
    claimWorkspace: vi.fn().mockResolvedValue({ link: link(TOKEN) }),
    ...overrides,
  } as unknown as ApiClient & WorkspaceApiClient & MemoryApiClient;
}

function mount(client: ApiClient, language: "en" | "es" = "en") {
  return renderWithI18n(<ServerConfigProvider api={client}><ImportWizard api={client} /></ServerConfigProvider>, language);
}

function openWithHash(token: string) {
  window.history.replaceState(null, "", `/#w=${token}`);
}

afterEach(() => {
  vi.restoreAllMocks();
  window.history.replaceState(null, "", "/");
});

describe("opening a personal link (U6d)", () => {
  it("removes the hash from the URL at once and claims when there is no workspace yet", async () => {
    openWithHash(TOKEN);
    const replace = vi.spyOn(window.history, "replaceState");
    const client = api(CONFIG, { currentWorkspace: vi.fn().mockResolvedValue(null) });
    mount(client);

    await waitFor(() => expect(client.claimWorkspace).toHaveBeenCalledWith(TOKEN));
    expect(window.location.hash).toBe("");
    expect(replace).toHaveBeenCalled();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    await waitFor(() => expect(client.workspace).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("Your private space")).toBeInTheDocument();
  });

  it("claims before it asks for the workspace link, so the claimed cookie is the one used", async () => {
    openWithHash(TOKEN);
    const order: string[] = [];
    const client = api(CONFIG, {
      claimWorkspace: vi.fn(() => { order.push("claim"); return Promise.resolve({ link: link(TOKEN) }); }),
      workspace: vi.fn(() => { order.push("workspace"); return Promise.resolve({ link: link(TOKEN) }); }),
    });
    mount(client);

    await waitFor(() => expect(order).toEqual(["claim", "workspace"]));
  });

  it("keeps the path and query when it strips the hash", async () => {
    window.history.replaceState(null, "", `/?lang=es#w=${TOKEN}`);
    mount(api(CONFIG));

    await waitFor(() => expect(window.location.hash).toBe(""));
    expect(window.location.pathname + window.location.search).toBe("/?lang=es");
  });

  it("strips the hash even when workspaces is off, and claims nothing", async () => {
    openWithHash(TOKEN);
    const client = api({ model_provider: "gemini", demo: true, workspaces: false });
    mount(client);

    await waitFor(() => expect(window.location.hash).toBe(""));
    await screen.findByLabelText("Supplier name");
    expect(client.claimWorkspace).not.toHaveBeenCalled();
    expect(client.currentWorkspace).not.toHaveBeenCalled();
  });

  it("claims directly, without asking, when the link is the current workspace", async () => {
    openWithHash(TOKEN);
    const client = api(CONFIG, { currentWorkspace: vi.fn().mockResolvedValue({ link: link(TOKEN) }) });
    mount(client);

    await waitFor(() => expect(client.claimWorkspace).toHaveBeenCalledWith(TOKEN));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("asks before switching when the link is a different workspace, and claims nothing yet", async () => {
    openWithHash(TOKEN);
    const client = api(CONFIG, { currentWorkspace: vi.fn().mockResolvedValue({ link: link(OTHER) }) });
    mount(client);

    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("This link opens another private space. If you switch, your current space can only be recovered with its own link.");
    expect(screen.getByRole("button", { name: "Switch space" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stay in the current one" })).toBeInTheDocument();
    expect(client.claimWorkspace).not.toHaveBeenCalled();
    expect(client.workspace).not.toHaveBeenCalled();
    expect(window.location.hash).toBe("");
  });

  it("is in Spanish with the usted register", async () => {
    openWithHash(TOKEN);
    mount(api(CONFIG, { currentWorkspace: vi.fn().mockResolvedValue({ link: link(OTHER) }) }), "es");

    expect(await screen.findByRole("alertdialog")).toHaveTextContent(
      "Este enlace abre otro espacio privado. Si cambia, su espacio actual solo podrá recuperarse con su propio enlace.",
    );
    expect(screen.getByRole("button", { name: "Cambiar de espacio" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Quedarme en el actual" })).toBeInTheDocument();
  });

  it("claims and continues when the user chooses to switch", async () => {
    openWithHash(TOKEN);
    const client = api(CONFIG, { currentWorkspace: vi.fn().mockResolvedValue({ link: link(OTHER) }) });
    mount(client);

    await userEvent.click(await screen.findByRole("button", { name: "Switch space" }));

    await waitFor(() => expect(client.claimWorkspace).toHaveBeenCalledWith(TOKEN));
    await waitFor(() => expect(client.workspace).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(await screen.findByText("Your private space")).toBeInTheDocument();
  });

  it("keeps the current workspace, with no claim call, when the user stays", async () => {
    openWithHash(TOKEN);
    const client = api(CONFIG, { currentWorkspace: vi.fn().mockResolvedValue({ link: link(OTHER) }) });
    mount(client);

    await userEvent.click(await screen.findByRole("button", { name: "Stay in the current one" }));

    await waitFor(() => expect(client.workspace).toHaveBeenCalledTimes(1));
    expect(client.claimWorkspace).not.toHaveBeenCalled();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(await screen.findByText("Your private space")).toBeInTheDocument();
  });

  it("holds the data calls back while the question is open", async () => {
    openWithHash(TOKEN);
    const client = api(CONFIG, {
      currentWorkspace: vi.fn().mockResolvedValue({ link: link(OTHER) }),
      listMemories: vi.fn().mockResolvedValue([]),
    });
    mount(client);

    await screen.findByRole("alertdialog");
    expect(client.listMemories).not.toHaveBeenCalled();
  });

  it("never asks and never claims when the page opens without a link", async () => {
    const client = api(CONFIG);
    mount(client);

    expect(await screen.findByText("Your private space")).toBeInTheDocument();
    expect(client.currentWorkspace).not.toHaveBeenCalled();
    expect(client.claimWorkspace).not.toHaveBeenCalled();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("ignores a hash that is not a workspace token", async () => {
    window.history.replaceState(null, "", "/#other=1");
    const client = api(CONFIG);
    mount(client);

    expect(await screen.findByText("Your private space")).toBeInTheDocument();
    expect(client.claimWorkspace).not.toHaveBeenCalled();
    expect(window.location.hash).toBe("#other=1");
  });

  it("still continues with a workspace when the claim is refused", async () => {
    openWithHash(TOKEN);
    const client = api(CONFIG, {
      claimWorkspace: vi.fn().mockRejectedValue(new ApiError(404, "workspace_not_found", "none")),
    });
    mount(client);

    await waitFor(() => expect(client.workspace).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("Your private space")).toBeInTheDocument();
  });
});
