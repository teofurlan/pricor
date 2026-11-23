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
    await screen.findByLabelText("Price list file");
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

    await userEvent.click(await screen.findByRole("button", { name: "Switch space" }, { timeout: 3000 }));

    await waitFor(() => expect(client.claimWorkspace).toHaveBeenCalledWith(TOKEN));
    await waitFor(() => expect(client.workspace).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("keeps the current workspace, with no claim call, when the user stays", async () => {
    openWithHash(TOKEN);
    const client = api(CONFIG, { currentWorkspace: vi.fn().mockResolvedValue({ link: link(OTHER) }) });
    mount(client);

    await userEvent.click(await screen.findByRole("button", { name: "Stay in the current one" }));

    await waitFor(() => expect(client.workspace).toHaveBeenCalledTimes(1));
    expect(client.claimWorkspace).not.toHaveBeenCalled();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
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

    await waitFor(() => expect(client.workspace).toHaveBeenCalledTimes(1));
    expect(client.currentWorkspace).not.toHaveBeenCalled();
    expect(client.claimWorkspace).not.toHaveBeenCalled();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("ignores a hash that is not a workspace token", async () => {
    window.history.replaceState(null, "", "/#other=1");
    const client = api(CONFIG);
    mount(client);

    await waitFor(() => expect(client.workspace).toHaveBeenCalledTimes(1));
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
  });
});

describe("Google Sign-In in workspace (S1, S3, S4)", () => {
  const GOOGLE_CONFIG: ServerConfig = {
    model_provider: "gemini",
    demo: true,
    workspaces: true,
    google_client_id: "google-client-123",
  };

  afterEach(() => {
    delete (window as unknown as { __pricorGooglePrompt?: unknown }).__pricorGooglePrompt;
  });

  function installGooglePrompt(credential = "google-id-token") {
    (window as unknown as { __pricorGooglePrompt?: (cb: (cred: string) => void) => void }).__pricorGooglePrompt = (cb) => {
      cb(credential);
    };
  }

  it("links the current workspace with Google and shows the linked email", async () => {
    installGooglePrompt("cred-1");
    const googleSignIn = vi.fn().mockResolvedValue({
      status: "linked",
      link: link(OTHER),
      account: { email: "user@example.com" },
    });
    const client = api(GOOGLE_CONFIG, { googleSignIn });
    mount(client);

    await userEvent.click(await screen.findByRole("button", { name: "Continue with Google" }));

    await waitFor(() => expect(googleSignIn).toHaveBeenCalledWith("cred-1", "auto"));
    expect(await screen.findByText("Your suppliers are saved to user@example.com")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Continue with Google" })).not.toBeInTheDocument();
  });

  it("switches directly when googleSignIn returns status 'switched' and reloads workspace-scoped data", async () => {
    installGooglePrompt("cred-2");
    const googleSignIn = vi.fn().mockResolvedValue({
      status: "switched",
      link: link(TOKEN),
      account: { email: "user@example.com" },
    });
    const getOutputFormat = vi.fn().mockResolvedValue(null);
    const listMemories = vi.fn().mockResolvedValue([]);
    const client = api(GOOGLE_CONFIG, { googleSignIn, getOutputFormat, listMemories });
    mount(client);

    await screen.findByRole("button", { name: "Continue with Google" });
    await waitFor(() => expect(getOutputFormat).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(listMemories).toHaveBeenCalledTimes(1));

    await userEvent.click(screen.getByRole("button", { name: "Continue with Google" }));

    expect(await screen.findByText("Your suppliers are saved to user@example.com")).toBeInTheDocument();
    await waitFor(() => expect(getOutputFormat).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(listMemories).toHaveBeenCalledTimes(2));
  });

  it("opens conflict dialog and resolves with 'Open my account's space' (use_account)", async () => {
    installGooglePrompt("cred-conflict");
    const googleSignIn = vi
      .fn()
      .mockResolvedValueOnce({
        status: "conflict",
        link: link(OTHER),
        account: { email: "user@example.com" },
      })
      .mockResolvedValueOnce({
        status: "switched",
        link: link(TOKEN),
        account: { email: "user@example.com" },
      });
    const getOutputFormat = vi.fn().mockResolvedValue(null);
    const listMemories = vi.fn().mockResolvedValue([]);
    const client = api(GOOGLE_CONFIG, { googleSignIn, getOutputFormat, listMemories });
    mount(client);

    await userEvent.click(await screen.findByRole("button", { name: "Continue with Google" }));

    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Your Google account (user@example.com) already has another saved space.");

    await userEvent.click(screen.getByRole("button", { name: "Open my account's space" }));

    await waitFor(() => expect(googleSignIn).toHaveBeenNthCalledWith(2, "cred-conflict", "use_account"));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(await screen.findByText("Your suppliers are saved to user@example.com")).toBeInTheDocument();
    await waitFor(() => expect(getOutputFormat).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(listMemories).toHaveBeenCalledTimes(2));
  });

  it("resolves conflict dialog with 'Save current space to my account' (link_current) or cancels", async () => {
    installGooglePrompt("cred-conflict-2");
    const googleSignIn = vi
      .fn()
      .mockResolvedValueOnce({
        status: "conflict",
        link: link(OTHER),
        account: { email: "user@example.com" },
      })
      .mockResolvedValueOnce({
        status: "conflict",
        link: link(OTHER),
        account: { email: "user@example.com" },
      })
      .mockResolvedValueOnce({
        status: "linked",
        link: link(OTHER),
        account: { email: "user@example.com" },
      });
    const client = api(GOOGLE_CONFIG, { googleSignIn });
    mount(client);

    await userEvent.click(await screen.findByRole("button", { name: "Continue with Google" }));
    await screen.findByRole("alertdialog");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(googleSignIn).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole("button", { name: "Continue with Google" }));
    await screen.findByRole("alertdialog");
    await userEvent.click(screen.getByRole("button", { name: "Save current space to my account" }));

    await waitFor(() => expect(googleSignIn).toHaveBeenNthCalledWith(3, "cred-conflict-2", "link_current"));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(await screen.findByText("Your suppliers are saved to user@example.com")).toBeInTheDocument();
  });

  it("unlinks the Google account when Unlink account is clicked", async () => {
    const unlinkGoogleAccount = vi.fn().mockResolvedValue({ link: link(OTHER), account: null });
    const client = api(GOOGLE_CONFIG, {
      workspace: vi.fn().mockResolvedValue({ link: link(OTHER), account: { email: "user@example.com" } }),
      unlinkGoogleAccount,
    });
    mount(client);

    expect(await screen.findByText("Your suppliers are saved to user@example.com")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Unlink account" }));

    await waitFor(() => expect(unlinkGoogleAccount).toHaveBeenCalledTimes(1));
    expect(await screen.findByRole("button", { name: "Continue with Google" })).toBeInTheDocument();
    expect(screen.queryByText("Your suppliers are saved to user@example.com")).not.toBeInTheDocument();
  });

  it("renders conflict dialog and Google verification error in Spanish (usted)", async () => {
    installGooglePrompt("cred-es");
    const googleSignIn = vi
      .fn()
      .mockRejectedValueOnce(new ApiError(401, "invalid_google_token", "bad token"))
      .mockResolvedValueOnce({
        status: "conflict",
        link: link(OTHER),
        account: { email: "user@example.com" },
      });
    const client = api(GOOGLE_CONFIG, { googleSignIn });
    mount(client, "es");

    await userEvent.click(await screen.findByRole("button", { name: "Continuar con Google" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "No pudimos verificar su cuenta de Google. Intente de nuevo.",
    );

    await userEvent.click(screen.getByRole("button", { name: "Continuar con Google" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent(
      "Su cuenta de Google (user@example.com) ya tiene otro espacio guardado. ¿Quiere abrir el espacio de su cuenta o guardar el espacio actual en su cuenta?",
    );
    expect(screen.getByRole("button", { name: "Abrir el espacio de mi cuenta" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Guardar el espacio actual en mi cuenta" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancelar" })).toBeInTheDocument();
  });
});
