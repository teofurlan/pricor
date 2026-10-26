import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { ApiClient, SampleApiClient } from "../api/client";
import { ServerConfigProvider } from "../api/serverConfig";
import type { SampleListing } from "../api/types";
import { session } from "../test/fixtures";
import { renderWithI18n } from "../test/render";
import { ImportWizard } from "./ImportWizard";

const listing: SampleListing = {
  id: "demo-1",
  file_name: "demo-semana-1.xlsx",
  supplier_name: "Distribuidora Ejemplo",
  week: 1,
  title: { en: "Example distributor, week 1", es: "Distribuidora Ejemplo, semana 1" },
  description: { en: "About 300 products.", es: "Unos 300 productos." },
};

function api(overrides: Partial<ApiClient & SampleApiClient>): ApiClient & SampleApiClient {
  return {
    listSheets: vi.fn().mockResolvedValue([]),
    getSample: vi.fn().mockResolvedValue({ header: [], rows: [] }),
    exportSheet: vi.fn().mockResolvedValue({ header: [], rows: [], total: 0 }),
    createImport: vi.fn().mockResolvedValue(session({ status: "questions_pending" })),
    config: vi.fn().mockResolvedValue({ model_provider: "gemini", demo: true }),
    listSamples: vi.fn().mockResolvedValue([listing]),
    downloadSample: vi.fn().mockResolvedValue(new File(["x"], "demo-semana-1.xlsx")),
    ...overrides,
  } as unknown as ApiClient & SampleApiClient;
}

describe("ImportWizard samples", () => {
  it("starts an import from a sample list", async () => {
    const client = api({});
    renderWithI18n(<ServerConfigProvider api={client}><ImportWizard api={client} /></ServerConfigProvider>);

    await userEvent.click(await screen.findByRole("button", { name: /Example distributor, week 1/ }));
    await waitFor(() => expect(screen.getByLabelText("Supplier name")).toHaveValue("Distribuidora Ejemplo"));
    await userEvent.click(await screen.findByRole("button", { name: "Start import" }));

    await waitFor(() => expect(client.createImport).toHaveBeenCalled());
    const input = (client.createImport as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(input.file.name).toBe("demo-semana-1.xlsx");
    expect(input.supplierName).toBe("Distribuidora Ejemplo");
  });

  it("works without sample support in the client", async () => {
    const client = api({ listSamples: undefined, downloadSample: undefined });
    renderWithI18n(<ServerConfigProvider api={client}><ImportWizard api={client} /></ServerConfigProvider>);

    expect(await screen.findByLabelText("Supplier name")).toBeInTheDocument();
    expect(screen.queryByText("Try a sample list")).not.toBeInTheDocument();
  });
});
