import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ApiClient } from "./client";
import { isHosted, ServerConfigProvider, useServerConfig } from "./serverConfig";

function Consumer() {
  const { hosted, config } = useServerConfig();
  return (
    <div>
      <span data-testid="hosted">{hosted ? "hosted" : "local"}</span>
      <span data-testid="provider">{config?.model_provider ?? "none"}</span>
    </div>
  );
}

describe("serverConfig", () => {
  it("determines hosted status accurately", () => {
    expect(isHosted(null)).toBe(false);
    expect(isHosted(undefined)).toBe(false);
    expect(isHosted({ model_provider: "ollama", demo: false })).toBe(false);
    expect(isHosted({ model_provider: "gemini", demo: false })).toBe(true);
    expect(isHosted({ model_provider: "ollama", demo: true })).toBe(true);
    expect(isHosted({ model_provider: "gemini", demo: true })).toBe(true);
  });

  it("defaults to local mode outside a provider", () => {
    render(<Consumer />);
    expect(screen.getByTestId("hosted")).toHaveTextContent("local");
  });

  it("loads config from ApiClient and updates to hosted", async () => {
    const api = {
      config: vi.fn().mockResolvedValue({ model_provider: "gemini", demo: false }),
    } as unknown as ApiClient;

    render(
      <ServerConfigProvider api={api}>
        <Consumer />
      </ServerConfigProvider>,
    );

    expect(screen.getByTestId("hosted")).toHaveTextContent("local");
    await waitFor(() => expect(screen.getByTestId("hosted")).toHaveTextContent("hosted"));
    expect(screen.getByTestId("provider")).toHaveTextContent("gemini");
  });

  it("falls back to local mode when api.config() fails", async () => {
    const api = {
      config: vi.fn().mockRejectedValue(new Error("500")),
    } as unknown as ApiClient;

    render(
      <ServerConfigProvider api={api}>
        <Consumer />
      </ServerConfigProvider>,
    );

    expect(screen.getByTestId("hosted")).toHaveTextContent("local");
    // Wait a tick to ensure promise rejection was handled
    await new Promise((r) => setTimeout(r, 10));
    expect(screen.getByTestId("hosted")).toHaveTextContent("local");
  });
});
