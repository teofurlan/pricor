import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import { column, previewItem, previewPage, question } from "../../test/fixtures";
import { renderWithI18n } from "../../test/render";
import { I18nProvider, useI18n } from "../../i18n";
import { ApprovePanel } from "./ApprovePanel";
import { ColumnsTable } from "./ColumnsTable";
import { ErrorBanner } from "./ErrorBanner";
import { HeaderChoice } from "./HeaderChoice";
import { LanguageToggle } from "./LanguageToggle";
import { PreviewTable } from "./PreviewTable";
import { QuestionsPanel } from "./QuestionsPanel";
import { RejectedList } from "./RejectedList";
import { Stepper, type StepItem } from "./Stepper";
import { UploadForm } from "./UploadForm";

describe("UploadForm", () => {
  const supplierOf = (name: string) => screen.getByLabelText(`Supplier for ${name}`);

  it("cannot start until there is a file with a supplier name", async () => {
    renderWithI18n(<UploadForm busy={false} onSubmit={vi.fn()} />);
    const start = screen.getByRole("button", { name: "Start import" });
    expect(start).toBeDisabled();

    await userEvent.upload(screen.getByLabelText("Price list file"), new File(["a"], "Ferreteria_lista.csv"));
    expect(supplierOf("Ferreteria_lista.csv")).toHaveValue("Ferreteria");
    expect(start).toBeEnabled();

    await userEvent.clear(supplierOf("Ferreteria_lista.csv"));
    expect(start).toBeDisabled();
  });

  it("submits the supplier, file, optional sheet and language for a multi-sheet file", async () => {
    const onSubmit = vi.fn();
    const onInspectSheets = vi.fn().mockResolvedValue(["Hoja 1", "Hoja 2"]);
    renderWithI18n(<UploadForm busy={false} onSubmit={onSubmit} onInspectSheets={onInspectSheets} />);
    const file = new File(["a"], "catalogo.xlsx");
    await userEvent.upload(screen.getByLabelText("Price list file"), file);
    await userEvent.clear(supplierOf("catalogo.xlsx"));
    await userEvent.type(supplierOf("catalogo.xlsx"), "Acme");

    const sheetSelect = await screen.findByLabelText("Sheet for catalogo.xlsx");
    expect(sheetSelect).toHaveValue("");
    expect(within(sheetSelect).getByRole("option", { name: "First sheet with data" })).toHaveValue("");

    await userEvent.selectOptions(sheetSelect, "Hoja 2");
    await userEvent.selectOptions(screen.getByLabelText("Language of the questions"), "es");
    await userEvent.click(screen.getByRole("button", { name: "Start import" }));

    expect(onSubmit).toHaveBeenCalledWith({ file, supplierName: "Acme", sheet: "Hoja 2", language: "es" });
  });

  it("replaces the file when only one is accepted, and ignores the sheets of the file it replaced", async () => {
    const answers: Record<string, (names: string[]) => void> = {};
    const onInspectSheets = vi.fn((file: File) => new Promise<string[]>((resolve) => { answers[file.name] = resolve; }));
    renderWithI18n(<UploadForm busy={false} onSubmit={vi.fn()} onInspectSheets={onInspectSheets} />);
    await userEvent.upload(screen.getByLabelText("Price list file"), new File(["a"], "primero.xlsx"));
    await userEvent.upload(screen.getByLabelText("Price list file"), new File(["b"], "segundo.xlsx"));
    answers["segundo.xlsx"](["Nueva 1", "Nueva 2"]);
    const sheet = await screen.findByLabelText("Sheet for segundo.xlsx");
    answers["primero.xlsx"](["Vieja 1", "Vieja 2"]);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByLabelText("Sheet for primero.xlsx")).toBeNull();
    expect(screen.queryByLabelText("Supplier for primero.xlsx")).toBeNull();
    expect(within(sheet).getByRole("option", { name: "Nueva 1" })).toBeInTheDocument();
  });

  it("says so when the sheets of a file cannot be read", async () => {
    const onInspectSheets = vi.fn().mockRejectedValue(new ApiError(415, "unsupported_format", "unsupported file type"));
    renderWithI18n(<UploadForm busy={false} onSubmit={vi.fn()} onInspectSheets={onInspectSheets} />);
    await userEvent.upload(screen.getByLabelText("Price list file"), new File(["a"], "lista.xlsx"));
    expect(await screen.findByText("Could not read this file: unsupported file type")).toBeInTheDocument();
  });

  it("hides the sheet select when the file has only one sheet or is single-sheet csv", async () => {
    const onSubmit = vi.fn();
    const onInspectSheets = vi.fn().mockResolvedValue(["lista_octubre"]);
    renderWithI18n(<UploadForm busy={false} onSubmit={onSubmit} onInspectSheets={onInspectSheets} />);
    const file = new File(["a"], "lista.csv");
    await userEvent.upload(screen.getByLabelText("Price list file"), file);
    await waitFor(() => expect(onInspectSheets).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(screen.queryByLabelText(/Sheet for/)).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Start import" }));
    expect(onSubmit).toHaveBeenCalledWith({ file, supplierName: "lista", sheet: "", language: "en" });
  });

  it("renders drop zone copy, nests the file input for focus rings, and changes text on dragover", () => {
    renderWithI18n(<UploadForm busy={false} onSubmit={vi.fn()} />);
    const dropzone = document.querySelector(".dropzone");
    expect(dropzone).toBeInTheDocument();
    expect(dropzone?.contains(screen.getByLabelText("Price list file"))).toBe(true);
    expect(within(dropzone as HTMLElement).getByText("Drag your price list here")).toBeInTheDocument();
    expect(within(dropzone as HTMLElement).getByText("or")).toBeInTheDocument();
    expect(within(dropzone as HTMLElement).getByText("Choose file")).toBeInTheDocument();
    expect(within(dropzone as HTMLElement).getByText("Excel (.xls, .xlsx) or CSV · up to 20 MB")).toBeInTheDocument();

    const file = new File(["col1,col2"], "test.csv", { type: "text/csv" });
    fireEvent.dragOver(dropzone!, { dataTransfer: { files: [file] } });
    expect(within(dropzone as HTMLElement).getByText("Drop it to read it")).toBeInTheDocument();

    fireEvent.dragLeave(dropzone!);
    expect(within(dropzone as HTMLElement).getByText("Drag your price list here")).toBeInTheDocument();
  });

  it("renders drop zone copy and dragover text in Spanish", () => {
    renderWithI18n(<UploadForm busy={false} onSubmit={vi.fn()} />, "es");
    const dropzone = document.querySelector(".dropzone");
    expect(dropzone).toBeInTheDocument();
    expect(within(dropzone as HTMLElement).getByText("Arrastre su lista de precios aquí")).toBeInTheDocument();
    expect(within(dropzone as HTMLElement).getByText("o")).toBeInTheDocument();
    expect(within(dropzone as HTMLElement).getByText("Seleccionar archivo")).toBeInTheDocument();
    expect(within(dropzone as HTMLElement).getByText("Excel (.xls, .xlsx) o CSV · hasta 20 MB")).toBeInTheDocument();

    const file = new File(["col1,col2"], "test.csv", { type: "text/csv" });
    fireEvent.dragOver(dropzone!, { dataTransfer: { files: [file] } });
    expect(within(dropzone as HTMLElement).getByText("Suéltela para leerla")).toBeInTheDocument();
  });

  it("shows a chosen file as a tile with its type mark, name, extension and size, then the key to change it", async () => {
    renderWithI18n(<UploadForm busy={false} onSubmit={vi.fn()} />);
    const file = new File(["a".repeat(1536)], "precios-semana-42.csv", { type: "text/csv" });
    await userEvent.upload(screen.getByLabelText("Price list file"), file);

    expect(document.querySelector(".dropzone")).toBeNull();
    const tiles = within(screen.getByRole("list", { name: "Chosen files" })).getAllByRole("listitem");
    expect(tiles).toHaveLength(2);
    expect(within(tiles[0]).getByText("CSV")).toBeInTheDocument();
    expect(within(tiles[0]).getByText("precios-semana-42")).toBeInTheDocument();
    expect(within(tiles[0]).getByText(".csv")).toBeInTheDocument();
    expect(within(tiles[0]).getByText("1.5 KB")).toBeInTheDocument();
    expect(within(tiles[0]).getByRole("button", { name: "Remove precios-semana-42.csv" })).toBeInTheDocument();
    expect(within(tiles[1]).getByRole("button", { name: "Change file" })).toBeInTheDocument();
  });

  it("marks each kind of price list with its own type", async () => {
    renderWithI18n(<UploadForm busy={false} onSubmit={vi.fn()} onSubmitMany={vi.fn()} />);
    await userEvent.upload(screen.getByLabelText("Price list file"), [
      new File(["a"], "a.xlsx"), new File(["b"], "b.XLS"), new File(["c"], "c.xlsm"), new File(["d"], "d.csv"),
    ]);
    const tiles = within(screen.getByRole("list", { name: "Chosen files" })).getAllByRole("listitem");
    expect(tiles.slice(0, 4).map((tile) => tile.querySelector(".file-mark")?.getAttribute("data-kind"))).toEqual(["xlsx", "xls", "xlsm", "csv"]);
    expect(within(tiles[1]).getByText("XLS")).toBeInTheDocument();
    expect(within(tiles[1]).getByText(".XLS")).toBeInTheDocument();
  });

  it("accepts only one dropped file when the form takes one file", async () => {
    renderWithI18n(<UploadForm busy={false} onSubmit={vi.fn()} />);
    const dropzone = document.querySelector(".dropzone");
    expect(dropzone).not.toHaveClass("dropzone--active");

    const file1 = new File(["1"], "primero.csv", { type: "text/csv" });
    const file2 = new File(["2"], "segundo.csv", { type: "text/csv" });
    fireEvent.dragOver(dropzone!, { dataTransfer: { files: [file1] } });
    expect(dropzone).toHaveClass("dropzone--active");
    fireEvent.dragLeave(dropzone!);
    expect(dropzone).not.toHaveClass("dropzone--active");

    fireEvent.drop(dropzone!, { dataTransfer: { files: [file1, file2] } });

    expect(screen.getByText("primero")).toBeInTheDocument();
    expect(screen.queryByText("segundo")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Change file" })).toBeInTheDocument();
    expect(screen.getByLabelText("Price list file")).toBeInTheDocument();
  });

  it("adds files sideways with the add key always last, and lists one supplier per file below", async () => {
    const onSubmit = vi.fn();
    const onSubmitMany = vi.fn();
    renderWithI18n(<UploadForm busy={false} onSubmit={onSubmit} onSubmitMany={onSubmitMany} />);
    const first = new File(["a"], "Ferreteria_lista.csv");
    const second = new File(["b"], "acme-semana-3.xlsx");
    const third = new File(["c"], "Dipel.xlsx");
    await userEvent.upload(screen.getByLabelText("Price list file"), first);
    await userEvent.upload(screen.getByLabelText("Price list file"), [second, third]);

    const tray = screen.getByRole("list", { name: "Chosen files" });
    const tiles = within(tray).getAllByRole("listitem");
    expect(tiles).toHaveLength(4);
    expect(tiles.slice(0, 3).map((tile) => tile.querySelector(".file-tile__name")?.textContent)).toEqual(["Ferreteria_lista", "acme-semana-3", "Dipel"]);
    expect(within(tiles[3]).getByRole("button", { name: "Add files" })).toBeInTheDocument();
    expect(supplierOf("Ferreteria_lista.csv")).toHaveValue("Ferreteria");
    expect(supplierOf("acme-semana-3.xlsx")).toHaveValue("acme");
    expect(supplierOf("Dipel.xlsx")).toHaveValue("Dipel");

    await userEvent.click(within(tiles[1]).getByRole("button", { name: "Remove acme-semana-3.xlsx" }));
    expect(within(tray).getAllByRole("listitem")).toHaveLength(3);
    expect(screen.queryByLabelText("Supplier for acme-semana-3.xlsx")).toBeNull();

    await userEvent.type(supplierOf("Dipel.xlsx"), " SA");
    await userEvent.click(screen.getByRole("button", { name: "Start import" }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(onSubmitMany).toHaveBeenCalledWith([
      { file: first, supplierName: "Ferreteria", sheet: "", language: "en", forceFirstImport: false },
      { file: third, supplierName: "Dipel SA", sheet: "", language: "en", forceFirstImport: false },
    ]);
  });

  it("waits until sheet inspection finishes before enabling Start import", async () => {
    let resolveSheets!: (names: string[]) => void;
    const onInspectSheets = vi.fn(() => new Promise<string[]>((resolve) => { resolveSheets = resolve; }));
    renderWithI18n(<UploadForm busy={false} onSubmit={vi.fn()} onInspectSheets={onInspectSheets} />);
    await userEvent.upload(screen.getByLabelText("Price list file"), new File(["a"], "catalogo.xlsx"));

    const start = screen.getByRole("button", { name: "Start import" });
    expect(start).toBeDisabled();

    resolveSheets(["Hoja 1", "Hoja 2"]);
    await screen.findByLabelText("Sheet for catalogo.xlsx");
    expect(start).toBeEnabled();
  });

  it("keeps question language and start-from-scratch available when queuing several files", async () => {
    const onSubmitMany = vi.fn();
    renderWithI18n(<UploadForm busy={false} onSubmit={vi.fn()} onSubmitMany={onSubmitMany} />);
    const first = new File(["a"], "Ferreteria_lista.csv");
    const second = new File(["b"], "acme-semana-3.xlsx");
    await userEvent.upload(screen.getByLabelText("Price list file"), [first, second]);

    await userEvent.selectOptions(screen.getByLabelText("Language of the questions"), "es");
    await userEvent.click(screen.getByLabelText("Start from scratch instead of reusing the saved plan"));
    await userEvent.click(screen.getByRole("button", { name: "Start import" }));

    expect(onSubmitMany).toHaveBeenCalledWith([
      { file: first, supplierName: "Ferreteria", sheet: "", language: "es", forceFirstImport: true },
      { file: second, supplierName: "acme", sheet: "", language: "es", forceFirstImport: true },
    ]);
  });

  it("does not add the same file twice", async () => {
    renderWithI18n(<UploadForm busy={false} onSubmit={vi.fn()} onSubmitMany={vi.fn()} />);
    const file = new File(["a"], "lista.csv", { lastModified: 1 });
    await userEvent.upload(screen.getByLabelText("Price list file"), file);
    await userEvent.upload(screen.getByLabelText("Price list file"), file);
    expect(within(screen.getByRole("list", { name: "Chosen files" })).getAllByRole("listitem")).toHaveLength(2);
  });

  it("returns to the drop zone when the last file is removed", async () => {
    renderWithI18n(<UploadForm busy={false} onSubmit={vi.fn()} onSubmitMany={vi.fn()} />);
    await userEvent.upload(screen.getByLabelText("Price list file"), new File(["a"], "lista.csv"));
    await userEvent.click(screen.getByRole("button", { name: "Remove lista.csv" }));
    expect(document.querySelector(".dropzone")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Chosen files" })).toBeNull();
    expect(screen.getByRole("button", { name: "Start import" })).toBeDisabled();
  });

  it("starts a one-file import as before when only one file was added to a form that takes several", async () => {
    const onSubmit = vi.fn();
    const onSubmitMany = vi.fn();
    renderWithI18n(<UploadForm busy={false} onSubmit={onSubmit} onSubmitMany={onSubmitMany} />);
    const file = new File(["a"], "lista.csv");
    await userEvent.upload(screen.getByLabelText("Price list file"), file);
    await userEvent.click(screen.getByRole("button", { name: "Start import" }));
    expect(onSubmitMany).not.toHaveBeenCalled();
    expect(onSubmit).toHaveBeenCalledWith({ file, supplierName: "lista", sheet: "", language: "en" });
  });

  it("names the tiles and suppliers in Spanish", async () => {
    renderWithI18n(<UploadForm busy={false} onSubmit={vi.fn()} onSubmitMany={vi.fn()} />, "es");
    await userEvent.upload(screen.getByLabelText("Archivo de la lista de precios"), new File(["a"], "lista.csv"));
    expect(screen.getByRole("list", { name: "Archivos elegidos" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Quitar lista.csv" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Agregar archivos" })).toBeInTheDocument();
    expect(screen.getByLabelText("Proveedor de lista.csv")).toHaveValue("lista");
  });

  it("can ask to ignore the saved plan and start from scratch", async () => {
    const onSubmit = vi.fn();
    renderWithI18n(<UploadForm busy={false} onSubmit={onSubmit} />);
    const fresh = "Start from scratch instead of reusing the saved plan";
    await userEvent.upload(screen.getByLabelText("Price list file"), new File(["a"], "lista.csv"));
    await userEvent.clear(supplierOf("lista.csv"));
    await userEvent.type(supplierOf("lista.csv"), "Acme");
    expect(screen.getByLabelText(fresh)).not.toBeChecked();
    await userEvent.click(screen.getByLabelText(fresh));
    await userEvent.click(screen.getByRole("button", { name: "Start import" }));

    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ supplierName: "Acme", forceFirstImport: true }));
  });

  it("defaults the question language to the interface language", () => {
    renderWithI18n(<UploadForm busy={false} onSubmit={vi.fn()} />, "es");
    expect(screen.getByLabelText("Idioma de las preguntas")).toHaveValue("es");
  });

  it("is locked while an upload is running", () => {
    renderWithI18n(<UploadForm busy onSubmit={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Reading the file…" })).toBeDisabled();
  });

  it("renders loader with role='status' and aria-busy while upload is pending", () => {
    const { rerender } = renderWithI18n(<UploadForm busy onSubmit={vi.fn()} />);
    const loader = screen.getByRole("status");
    expect(loader).toHaveAttribute("aria-busy", "true");
    expect(loader).toHaveTextContent("Reading the file…");

    rerender(<UploadForm busy={false} onSubmit={vi.fn()} />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("renders smaller loader while onInspectSheets is pending after a file is chosen", async () => {
    let resolveSheets: (names: string[]) => void = () => {};
    const onInspectSheets = vi.fn().mockImplementation(() => new Promise<string[]>((res) => {
      resolveSheets = res;
    }));
    renderWithI18n(<UploadForm busy={false} onSubmit={vi.fn()} onInspectSheets={onInspectSheets} />);

    const file = new File(["a"], "catalogo.xlsx");
    await userEvent.upload(screen.getByLabelText("Price list file"), file);

    const smallLoader = screen.getByRole("status");
    expect(smallLoader).toHaveClass("tape-loader--small");
    expect(smallLoader).toHaveAttribute("aria-busy", "true");
    expect(smallLoader).toHaveTextContent("Reading the file…");

    resolveSheets(["Hoja 1", "Hoja 2"]);
    await screen.findByLabelText("Sheet for catalogo.xlsx");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("follows the UI language until changed by hand, then keeps the user value", async () => {
    function Harness() {
      const { setLanguage } = useI18n();
      return (
        <div>
          <button onClick={() => setLanguage("es")}>set-es</button>
          <button onClick={() => setLanguage("en")}>set-en</button>
          <UploadForm busy={false} onSubmit={vi.fn()} />
        </div>
      );
    }

    render(
      <I18nProvider initialLanguage="en">
        <Harness />
      </I18nProvider>,
    );

    const getSelect = () => screen.getByRole("combobox", { name: /questions|preguntas/i });
    expect(getSelect()).toHaveValue("en");

    // UI switches to Spanish -> select follows
    await userEvent.click(screen.getByRole("button", { name: "set-es" }));
    expect(getSelect()).toHaveValue("es");

    // UI switches back to English -> select follows
    await userEvent.click(screen.getByRole("button", { name: "set-en" }));
    expect(getSelect()).toHaveValue("en");

    // User changes select manually to Spanish
    await userEvent.selectOptions(getSelect(), "es");
    expect(getSelect()).toHaveValue("es");

    // UI switches to English -> select keeps user's manual choice
    await userEvent.click(screen.getByRole("button", { name: "set-en" }));
    expect(getSelect()).toHaveValue("es");

    // UI switches to Spanish -> select keeps user's manual choice
    await userEvent.click(screen.getByRole("button", { name: "set-es" }));
    expect(getSelect()).toHaveValue("es");
  });
});

describe("HeaderChoice", () => {
  const candidates = [
    { row_index: 0, file_row: 1, cells: ["LISTA OCTUBRE", "", ""] },
    { row_index: 1, file_row: 2, cells: ["Codigo", "Descripcion", "Precio"] },
  ];

  it("shows each candidate row with its file row number", () => {
    renderWithI18n(<HeaderChoice candidates={candidates} busy={false} onChoose={vi.fn()} />);
    expect(screen.getByRole("radio", { name: /Row 2.*Codigo/ })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Row 1.*LISTA OCTUBRE/ })).toBeInTheDocument();
  });

  it("sends the zero-based row index of the chosen candidate", async () => {
    const onChoose = vi.fn();
    renderWithI18n(<HeaderChoice candidates={candidates} busy={false} onChoose={onChoose} />);
    expect(screen.getByRole("button", { name: "Use this row" })).toBeDisabled();
    await userEvent.click(screen.getByRole("radio", { name: /Row 2/ }));
    await userEvent.click(screen.getByRole("button", { name: "Use this row" }));
    expect(onChoose).toHaveBeenCalledWith(1);
  });

  it("lets the user say the sheet has no header", async () => {
    const onChoose = vi.fn();
    renderWithI18n(<HeaderChoice candidates={candidates} busy={false} onChoose={onChoose} />);
    await userEvent.click(screen.getByRole("button", { name: "This sheet has no header row" }));
    expect(onChoose).toHaveBeenCalledWith(null);
  });
});

describe("ColumnsTable issues", () => {
  it("explains a column issue in Spanish", () => {
    renderWithI18n(<ColumnsTable columns={[column()]} issues={["no column was identified as the cost price"]} busy={false} onConfirm={vi.fn()} />, "es");
    expect(screen.getByText("ninguna columna se identificó como el precio de costo")).toBeInTheDocument();
  });
});

describe("ColumnsTable", () => {
  const columns = [
    column({ index: 0, header: "Codigo", role: "code", decided_by: "heuristics", score: 0.95, rationale: "heuristics: code (0.95)", samples: ["A1", "A2"], proposals: [{ stage: "heuristics", role: "code", score: 0.95, rationale: "code rule" }] }),
    column({ index: 1, header: "Precio", role: "cost_price", decided_by: "gemma", score: 0.7, rationale: "looks like a price", proposals: [{ stage: "gemma", role: "cost_price", score: 0.7, rationale: "price suggestion" }] }),
    column({ index: 2, header: "Misterio", role: null, decided_by: null, score: 0.2, samples: ["x"] }),
  ];

  it("shows Status column with plain language values instead of Decided by", () => {
    renderWithI18n(<ColumnsTable columns={columns} issues={[]} busy={false} onConfirm={vi.fn()} />);
    expect(screen.getByRole("columnheader", { name: "Status" })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Decided by" })).not.toBeInTheDocument();

    const rowCodigo = screen.getByRole("row", { name: /Codigo/ });
    expect(within(rowCodigo).getByText("✓ Automatically detected")).toBeInTheDocument();

    const rowMisterio = screen.getByRole("row", { name: /Misterio/ });
    expect(within(rowMisterio).getByText("Needs your confirmation")).toBeInTheDocument();
    expect(within(rowMisterio).queryByText("Needs your choice")).not.toBeInTheDocument();
  });

  it("renders 5-segment confidence meter, matching role label, and accessible label without raw score", () => {
    const colsWithProposals = [
      column({
        index: 0,
        header: "codart",
        role: "code",
        decided_by: "laya",
        score: 0.98,
        rationale: "laya: code (0.98)",
        proposals: [
          { stage: "laya", role: "code", score: 0.98, rationale: "laya: code (0.98)" },
          { stage: "gemma", role: "code", score: 0.65, rationale: "gemma: code (~0.65)" },
        ],
      }),
    ];
    renderWithI18n(<ColumnsTable columns={colsWithProposals} issues={[]} busy={false} onConfirm={vi.fn()} />);
    const row = screen.getByRole("row", { name: /codart/ });

    // Suggestion header
    expect(screen.getByRole("columnheader", { name: "Suggestion" })).toBeInTheDocument();

    // Suggested role uses role.* label: "Product code" (not raw "CODE")
    const suggestionCell = row.querySelector(".cell--suggestion") as HTMLElement;
    expect(within(suggestionCell).getByText("Product code")).toBeInTheDocument();

    // No raw .98 text
    expect(within(row).queryByText(".98")).not.toBeInTheDocument();
    expect(within(row).queryByText("0.98")).not.toBeInTheDocument();

    // 5-segment meter with sage level class
    const meter = within(row).getByRole("meter");
    expect(meter).toHaveAttribute("aria-label", "Automatic suggestion, high confidence (98 %)");
    const segments = meter.querySelectorAll(".meter__seg");
    expect(segments).toHaveLength(5);
    const filled = meter.querySelectorAll(".meter__seg--filled");
    expect(filled).toHaveLength(5); // round(0.98 * 5) = 5
    expect(meter).toHaveClass("meter--sage");
  });

  it("renders 5-segment confidence meter with right filled count and level class per color", () => {
    const testColumns = [
      column({
        index: 0,
        header: "col_high",
        role: "code",
        score: 0.98,
        proposals: [{ stage: "laya", role: "code", score: 0.98, rationale: "" }],
      }),
      column({
        index: 1,
        header: "col_mid",
        role: "description",
        score: 0.55,
        proposals: [{ stage: "heuristics", role: "description", score: 0.55, rationale: "" }],
      }),
      column({
        index: 2,
        header: "col_low",
        role: "barcode",
        score: 0.1,
        proposals: [{ stage: "gemma", role: "barcode", score: 0.1, rationale: "" }],
      }),
    ];
    renderWithI18n(<ColumnsTable columns={testColumns} issues={[]} busy={false} onConfirm={vi.fn()} />);

    // Row 0: 0.98 -> 5 segments filled, sage level
    const row0 = screen.getByRole("row", { name: /col_high/ });
    const meter0 = within(row0).getByRole("meter");
    expect(meter0).toHaveAttribute("aria-label", "Automatic suggestion, high confidence (98 %)");
    expect(meter0.querySelectorAll(".meter__seg")).toHaveLength(5);
    expect(meter0.querySelectorAll(".meter__seg--filled")).toHaveLength(5);
    expect(meter0).toHaveClass("meter--sage");

    // Row 1: 0.55 -> 3 segments filled, ochre level
    const row1 = screen.getByRole("row", { name: /col_mid/ });
    const meter1 = within(row1).getByRole("meter");
    expect(meter1.querySelectorAll(".meter__seg")).toHaveLength(5);
    expect(meter1.querySelectorAll(".meter__seg--filled")).toHaveLength(3);
    expect(meter1).toHaveClass("meter--ochre");

    // Row 2: 0.1 -> at least 1 filled segment, brick level
    const row2 = screen.getByRole("row", { name: /col_low/ });
    const meter2 = within(row2).getByRole("meter");
    expect(meter2.querySelectorAll(".meter__seg")).toHaveLength(5);
    expect(meter2.querySelectorAll(".meter__seg--filled")).toHaveLength(1);
    expect(meter2).toHaveClass("meter--brick");
  });

  it("enforces row action key visibility rules (normal suggestion, ignore suggestion, no suggestion)", async () => {
    const testCols = [
      column({ index: 0, header: "ColA", role: null, decided_by: null, proposals: [{ stage: "laya", role: "code", score: 0.8, rationale: "" }] }),
      column({ index: 1, header: "ColB", role: null, decided_by: null, proposals: [{ stage: "heuristics", role: "ignore", score: 0.9, rationale: "" }] }),
      column({ index: 2, header: "ColC", role: null, decided_by: null, proposals: [] }),
    ];
    renderWithI18n(<ColumnsTable columns={testCols} issues={[]} busy={false} onConfirm={vi.fn()} />);

    // Row 0 (suggestion is "code", not "ignore"): [✓ Accept], [⊘ Ignore], [Change ▾]
    const row0 = screen.getByRole("row", { name: /ColA/ });
    expect(within(row0).getByRole("button", { name: /Accept/i })).toBeInTheDocument();
    expect(within(row0).getByRole("button", { name: /Ignore/i })).toBeInTheDocument();
    expect(within(row0).getByRole("combobox", { name: /Change role/i })).toBeInTheDocument();

    // Row 1 (suggestion is "ignore"): only [✓ Accept] and [Change ▾], NO duplicate Ignore button
    const row1 = screen.getByRole("row", { name: /ColB/ });
    expect(within(row1).getByRole("button", { name: /Accept/i })).toBeInTheDocument();
    expect(within(row1).queryByRole("button", { name: /Ignore/i })).not.toBeInTheDocument();
    expect(within(row1).getByRole("combobox", { name: /Change role/i })).toBeInTheDocument();

    // Row 2 (no suggestion): [⊘ Ignore] and [Change ▾], NO Accept button
    const row2 = screen.getByRole("row", { name: /ColC/ });
    expect(within(row2).queryByRole("button", { name: /Accept/i })).not.toBeInTheDocument();
    expect(within(row2).getByRole("button", { name: /Ignore/i })).toBeInTheDocument();
    expect(within(row2).getByRole("combobox", { name: /Change role/i })).toBeInTheDocument();
  });

  it("names each role picker after its column, so a screen reader can tell them apart", () => {
    const cols = [
      column({ index: 0, header: "CODIGO", role: null, decided_by: null }),
      column({ index: 1, header: "COD_PROV", role: null, decided_by: null }),
    ];
    renderWithI18n(<ColumnsTable columns={cols} issues={[]} busy={false} onConfirm={vi.fn()} />, "es");

    expect(screen.getByRole("combobox", { name: "Cambiar rol de CODIGO" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Cambiar rol de COD_PROV" })).toBeInTheDocument();
  });

  it("keeps Accept and Ignore next to the role picker, which never replaces them", async () => {
    const cols = [
      column({ index: 0, header: "ColA", role: null, decided_by: null, proposals: [{ stage: "laya", role: "code", score: 0.8, rationale: "" }] }),
    ];
    renderWithI18n(<ColumnsTable columns={cols} issues={[]} busy={false} onConfirm={vi.fn()} />);
    const row = screen.getByRole("row", { name: /ColA/ });
    const picker = within(row).getByRole("combobox", { name: /Change role/i });

    // Opening the picker is not a mode: the row keys stay, and Accept still works.
    await userEvent.click(picker);
    expect(within(row).getByRole("button", { name: /Accept/i })).toBeInTheDocument();
    expect(within(row).getByRole("button", { name: /Ignore/i })).toBeInTheDocument();
    await userEvent.click(within(row).getByRole("button", { name: /Accept/i }));
    expect(within(row).getByText("✓ Confirmed by you")).toBeInTheDocument();
    expect(row.querySelector(".role-decision__value")).toHaveTextContent("Product code");
  });

  it("offers the role picker on columns the model already decided", async () => {
    const onConfirm = vi.fn();
    const cols = [column({ index: 0, header: "ColA", role: "code", decided_by: "heuristics" })];
    renderWithI18n(<ColumnsTable columns={cols} issues={[]} busy={false} onConfirm={onConfirm} />);
    const row = screen.getByRole("row", { name: /ColA/ });
    await userEvent.selectOptions(within(row).getByRole("combobox", { name: /Change role/i }), "barcode");
    expect(within(row).getByText("Barcode")).toBeInTheDocument();
    // The picker stays available to change the role again.
    expect(within(row).getByRole("combobox", { name: /Change role/i })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Confirm columns" }));
    expect(onConfirm).toHaveBeenCalledWith({ 0: "barcode" });
  });

  it("shows correct singular remaining count for columns in English and Spanish", () => {
    const cols = [
      column({ index: 0, header: "ColA", role: null, decided_by: null }),
    ];
    const { rerender } = renderWithI18n(
      <ColumnsTable columns={cols} issues={[]} busy={false} onConfirm={vi.fn()} />,
      "en",
    );
    expect(screen.getByText("1 still needs your choice.")).toBeInTheDocument();

    rerender(
      <ColumnsTable columns={cols} issues={[]} busy={false} onConfirm={vi.fn()} />,
      "es",
    );
    expect(screen.getByText("Falta 1 por elegir.")).toBeInTheDocument();
  });

  it("allows picking a role, shows chosen role with Back to suggestion, and Back to suggestion clears choice", async () => {
    renderWithI18n(<ColumnsTable columns={columns} issues={[]} busy={false} onConfirm={vi.fn()} />);
    const row = screen.getByRole("row", { name: /Misterio/ });

    const select = within(row).getByRole("combobox", { name: /Change role/i });

    // Choose Barcode
    await userEvent.selectOptions(select, "barcode");

    // Status updates to Confirmed by you
    expect(within(row).getByText("✓ Confirmed by you")).toBeInTheDocument();

    // Row shows chosen role and [↺ Back to suggestion]
    expect(within(row).getByText("Barcode")).toBeInTheDocument();
    const backBtn = within(row).getByRole("button", { name: /Back to suggestion/i });
    expect(backBtn).toBeInTheDocument();

    // Clicking Back to suggestion unsets choice
    await userEvent.click(backBtn);
    expect(within(row).getByText("Needs your confirmation")).toBeInTheDocument();
    expect(within(row).queryByRole("button", { name: /Back to suggestion/i })).not.toBeInTheDocument();
  });

  it("accepts all pending suggestions with Accept all suggestions key", async () => {
    const onConfirm = vi.fn();
    const cols = [
      column({ index: 0, header: "Col1", role: null, decided_by: null, proposals: [{ stage: "laya", role: "code", score: 0.9, rationale: "" }] }),
      column({ index: 1, header: "Col2", role: null, decided_by: null, proposals: [{ stage: "gemma", role: "cost_price", score: 0.8, rationale: "" }] }),
    ];
    renderWithI18n(<ColumnsTable columns={cols} issues={[]} busy={false} onConfirm={onConfirm} />);

    const confirmBtn = screen.getByRole("button", { name: "Confirm columns" });
    expect(confirmBtn).toBeDisabled();

    // Click Accept all suggestions
    const acceptAll = screen.getByRole("button", { name: /Accept all suggestions/i });
    await userEvent.click(acceptAll);

    // Both rows are now confirmed
    expect(confirmBtn).toBeEnabled();
    await userEvent.click(confirmBtn);
    expect(onConfirm).toHaveBeenCalledWith({ 0: "code", 1: "cost_price" });
  });

  it("lists role issues from the server", () => {
    renderWithI18n(
      <ColumnsTable columns={columns.slice(0, 1)} issues={["no column is marked as the cost"]} busy={false} onConfirm={vi.fn()} />,
    );
    expect(screen.getByText("no column is marked as the cost")).toBeInTheDocument();
  });

  it("animates the confirm key while the models work on the confirmed columns", async () => {
    const { rerender } = renderWithI18n(<ColumnsTable columns={columns.slice(0, 2)} issues={[]} busy={false} onConfirm={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Confirm columns" }));
    rerender(<ColumnsTable columns={columns.slice(0, 2)} issues={[]} busy onConfirm={vi.fn()} />);
    const confirm = screen.getByRole("button", { name: "Confirm columns" });
    expect(confirm).toHaveAttribute("aria-busy", "true");
    expect(confirm.querySelector(".tape-loader")).toBeInTheDocument();
    rerender(<ColumnsTable columns={columns.slice(0, 2)} issues={[]} busy={false} onConfirm={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Confirm columns" })).not.toHaveAttribute("aria-busy");
  });

  it("sends only the corrections, so confirming untouched columns changes nothing", async () => {
    const onConfirm = vi.fn();
    renderWithI18n(<ColumnsTable columns={columns.slice(0, 2)} issues={[]} busy={false} onConfirm={onConfirm} />);
    await userEvent.click(screen.getByRole("button", { name: "Confirm columns" }));
    expect(onConfirm).toHaveBeenCalledWith({});
  });

  it("renders live preview of first 5 rows below the table, updating live and hiding ignored columns", async () => {
    const sampleData = {
      header: ["Codigo", "Descripcion", "Costo", "Relleno"],
      rows: [
        ["A1", "Tornillo", "1210.00", "xxx"],
        ["A2", "Tuerca", "968.00", "yyy"],
        ["A3", "Arandela", "121.00", "zzz"],
        ["A4", "Clavo", "60.50", "aaa"],
        ["A5", "Taco", "1815.00", "bbb"],
      ],
    };
    const testColumns = [
      column({ index: 0, header: "Codigo", role: "code", decided_by: "heuristics" }),
      column({ index: 1, header: "Descripcion", role: null, decided_by: null }), // undecided
      column({ index: 2, header: "Costo", role: "cost_price", decided_by: "heuristics" }),
      column({ index: 3, header: "Relleno", role: "ignore", decided_by: "user" }), // ignored
    ];

    renderWithI18n(
      <ColumnsTable
        columns={testColumns}
        issues={[]}
        busy={false}
        onConfirm={vi.fn()}
        sample={sampleData}
      />,
    );

    // Section title
    expect(screen.getByRole("heading", { name: "Preview: first 5 rows" })).toBeInTheDocument();

    const previewTable = screen.getByTestId("sample-preview-table");
    expect(previewTable).toBeInTheDocument();

    // Column 0 is "code" -> header shows "Product code"
    expect(within(previewTable).getByText("Product code")).toBeInTheDocument();

    // Column 1 is undecided -> header shows original header "Descripcion" with muted ink
    const undecidedTh = within(previewTable).getByText("Descripcion");
    expect(undecidedTh).toHaveClass("preview-th--muted");

    // Column 2 is "cost_price" -> header shows "Cost price"
    expect(within(previewTable).getByText("Cost price")).toBeInTheDocument();

    // Column 3 is "ignore" -> hidden from preview
    expect(within(previewTable).queryByText("Relleno")).not.toBeInTheDocument();
    expect(within(previewTable).queryByText("xxx")).not.toBeInTheDocument();

    // Check data row contents
    expect(within(previewTable).getByText("A1")).toBeInTheDocument();
    expect(within(previewTable).getByText("Tornillo")).toBeInTheDocument();
    expect(within(previewTable).getByText("1210.00")).toBeInTheDocument();
    expect(within(previewTable).getByText("A5")).toBeInTheDocument();

    // Update live before saving: pick Description for Column 1
    const rowDesc = within(document.querySelector(".table--columns") as HTMLElement).getByRole("row", { name: /Descripcion/ });
    await userEvent.selectOptions(within(rowDesc).getByRole("combobox", { name: /Change role/i }), "description");

    // Header in preview table updates live to "Description" and loses muted ink
    expect(within(previewTable).getByText("Description")).not.toHaveClass("preview-th--muted");
  });
});

describe("QuestionsPanel", () => {
  const vat = question({
    id: "price_includes_vat",
    text: { en: "Include VAT?", es: "¿Incluye IVA?" },
    options: [{ token: "yes", label: { en: "Yes", es: "Sí" } }, { token: "no", label: { en: "No", es: "No" } }],
  });

  it("asks one question at a time and waits for the answers", () => {
    renderWithI18n(<QuestionsPanel questions={[question(), vat]} answers={{}} busy={false} onAnswer={vi.fn()} onContinue={vi.fn()} />);
    expect(screen.getAllByRole("group")).toHaveLength(1);
    expect(screen.getByRole("group", { name: "Which currency are the prices in?" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Include VAT?" })).toBeNull();
    expect(screen.getByRole("button", { name: "See the preview" })).toBeDisabled();
  });

  it("keeps answered questions above as a changeable history and shows the next one", async () => {
    const onAnswer = vi.fn();
    renderWithI18n(<QuestionsPanel questions={[question(), vat]} answers={{ currency: "ARS" }} busy={false} onAnswer={onAnswer} onContinue={vi.fn()} />);
    const history = screen.getByRole("list", { name: "Answered questions" });
    expect(within(history).getByText("Which currency are the prices in?")).toBeInTheDocument();
    expect(within(history).getByText("Argentine pesos (ARS)")).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Include VAT?" })).toBeInTheDocument();
    await userEvent.click(within(history).getByRole("button", { name: "Change" }));
    await userEvent.click(screen.getByRole("button", { name: /US dollars/ }));
    expect(onAnswer).toHaveBeenCalledWith("currency", "USD");
  });

  it("lets the user continue once none is open", async () => {
    const onContinue = vi.fn();
    renderWithI18n(<QuestionsPanel questions={[question()]} answers={{ currency: "ARS" }} busy={false} onAnswer={vi.fn()} onContinue={onContinue} />);
    await userEvent.click(screen.getByRole("button", { name: "See the preview" }));
    expect(onContinue).toHaveBeenCalled();
  });

  it("asks Gemma about the open question and marks its suggestion without choosing it", async () => {
    let resolve: (value: { reply: string; suggested_option: string | null }) => void = () => undefined;
    const onAsk = vi.fn(() => new Promise<{ reply: string; suggested_option: string | null }>((done) => { resolve = done; }));
    const onAnswer = vi.fn();
    renderWithI18n(<QuestionsPanel questions={[question()]} answers={{}} busy={false} onAnswer={onAnswer} onContinue={vi.fn()} onAsk={onAsk} />);
    await userEvent.type(screen.getByLabelText("Ask the assistant about this question"), "The list says $ only");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(onAsk).toHaveBeenCalledWith("currency", "The list says $ only", []);
    expect(screen.getByRole("button", { name: /Ask/ })).toHaveAttribute("aria-busy", "true");
    await act(async () => resolve({ reply: "A bare $ in an Argentine list usually means pesos.", suggested_option: "ARS" }));
    expect(screen.getByText("The list says $ only")).toBeInTheDocument();
    expect(screen.getByText("A bare $ in an Argentine list usually means pesos.")).toBeInTheDocument();
    const ars = screen.getByRole("button", { name: /Argentine pesos/ });
    expect(ars).toHaveAttribute("aria-pressed", "false");
    expect(ars).toHaveTextContent("Suggested in the conversation");
    expect(onAnswer).not.toHaveBeenCalled();
  });

  it("keeps the question answerable when the assistant cannot be reached", async () => {
    const onAsk = vi.fn().mockRejectedValue(new ApiError(503, "model_unavailable", "down"));
    renderWithI18n(<QuestionsPanel questions={[question()]} answers={{}} busy={false} onAnswer={vi.fn()} onContinue={vi.fn()} onAsk={onAsk} />);
    await userEvent.type(screen.getByLabelText("Ask the assistant about this question"), "Which one?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The assistant is unavailable right now. You can still answer with the buttons.");
    expect(screen.getByRole("button", { name: /Argentine pesos/ })).toBeEnabled();
  });

  it("says so when there is nothing to ask", () => {
    renderWithI18n(<QuestionsPanel questions={[]} answers={{}} busy={false} onAnswer={vi.fn()} onContinue={vi.fn()} />);
    expect(screen.getByText("Every question is answered.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "See the preview" })).toBeEnabled();
  });

  it("shows correct singular remaining count in English and Spanish", () => {
    const { rerender } = renderWithI18n(
      <QuestionsPanel questions={[question()]} answers={{}} busy={false} onAnswer={vi.fn()} onContinue={vi.fn()} />,
      "en",
    );
    expect(screen.getByText("1 still to answer.")).toBeInTheDocument();

    rerender(
      <QuestionsPanel questions={[question()]} answers={{}} busy={false} onAnswer={vi.fn()} onContinue={vi.fn()} />,
      "es",
    );
    expect(screen.getByText("Falta 1 por responder.")).toBeInTheDocument();
  });

  it("renders live preview under questions panel with final cost column showing — until computed", () => {
    const sampleData = {
      header: ["Codigo", "Precio"],
      rows: [
        ["A1", "1210.00"],
        ["A2", "968.00"],
      ],
    };
    const testColumns = [
      column({ index: 0, header: "Codigo", role: "code", decided_by: "user" }),
      column({ index: 1, header: "Precio", role: "cost_price", decided_by: "user" }),
    ];

    const { rerender } = renderWithI18n(
      <QuestionsPanel
        questions={[]}
        answers={{}}
        busy={false}
        onAnswer={vi.fn()}
        onContinue={vi.fn()}
        sample={sampleData}
        columns={testColumns}
      />,
    );

    // Section title
    expect(screen.getByRole("heading", { name: "Preview: first 5 rows" })).toBeInTheDocument();
    const previewTable = screen.getByTestId("sample-preview-table");

    // Final cost header exists
    expect(within(previewTable).getByText("Final cost")).toBeInTheDocument();

    // Shows — when not computed
    const dashes = within(previewTable).getAllByText("—");
    expect(dashes.length).toBeGreaterThanOrEqual(2);

    // Re-render with computed final costs
    rerender(
      <QuestionsPanel
        questions={[]}
        answers={{ currency: "ARS" }}
        busy={false}
        onAnswer={vi.fn()}
        onContinue={vi.fn()}
        sample={sampleData}
        columns={testColumns}
        finalCosts={["1000.00 ARS", "800.00 ARS"]}
      />,
    );

    expect(within(previewTable).getByText("1000.00 ARS")).toBeInTheDocument();
    expect(within(previewTable).getByText("800.00 ARS")).toBeInTheDocument();
  });
});

describe("PreviewTable", () => {
  it("shows the file row in the journal, with original cells, every step and final cost on the selected tape", async () => {
    renderWithI18n(<PreviewTable page={previewPage()} busy={false} onPage={vi.fn()} />);
    const row = screen.getByRole("button", { name: "Row 3" }).closest("tr")!;
    expect(within(row).queryByText("In your file")).toBeNull();
    const tape = screen.getByRole("region", { name: "From file to cost" });
    await userEvent.click(within(tape).getByText("In your file"));
    expect(within(tape).getByText("A1, Tornillo, 1.210,00, 21%")).toBeVisible();
    expect(await within(tape).findByText("VAT removed")).toBeInTheDocument();
    expect(
      await within(tape).findByText((_, el) => Boolean(el?.classList.contains("trace__value") && el?.textContent === "1,000.00 ARS")),
    ).toBeInTheDocument();
  });

  it("shows a rejected row with its file row number and reasons instead of a cost", () => {
    const rejected = previewItem({
      row_number: 8,
      status: "rejected",
      original: ["A6", "Brida", "abc", "21%"],
      trace: [],
      record: null,
      reasons: ["cost: cannot parse 'abc' as a number"],
    });
    renderWithI18n(<PreviewTable page={previewPage({ items: [rejected] })} busy={false} onPage={vi.fn()} />);
    const row = screen.getByRole("button", { name: "Row 8" }).closest("tr")!;
    expect(row).toHaveClass("row--rejected");
    expect(within(row).getByText("cost: cannot parse 'abc' as a number")).toBeInTheDocument();
    expect(within(row).getByText("Rejected")).toBeInTheDocument();
  });

  it("pages through the rows and says where the user is", async () => {
    const onPage = vi.fn();
    const page = previewPage({ offset: 0, limit: 1, total_items: 3 });
    renderWithI18n(<PreviewTable page={page} busy={false} onPage={onPage} />);
    expect(screen.getByText("Rows 1–1 of 3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(onPage).toHaveBeenCalledWith(1);
  });
});

describe("RejectedList", () => {
  it("lists every rejected row by its number in the supplier's file", () => {
    renderWithI18n(<RejectedList rows={previewPage().totals.rejected_rows} />);
    const item = screen.getByRole("listitem");
    expect(item).toHaveTextContent("Row 8");
    expect(item).toHaveTextContent("cannot parse 'abc'");
  });

  it("says plainly when nothing was rejected", () => {
    renderWithI18n(<RejectedList rows={[]} />);
    expect(screen.getByText("No rows were rejected.")).toBeInTheDocument();
  });

  it("paginates very long rejected lists in batches of 50", async () => {
    const many = Array.from({ length: 65 }, (_, index) => ({ row_number: index + 2, reasons: [`bad row ${index + 2}`] }));
    renderWithI18n(<RejectedList rows={many} />);
    expect(screen.getAllByRole("listitem")).toHaveLength(50);
    await userEvent.click(screen.getByRole("button", { name: "Show more (15 left)" }));
    expect(screen.getAllByRole("listitem")).toHaveLength(65);
  });
});

describe("ApprovePanel", () => {
  const links = {
    products: { csv: "/imports/s1/export?format=csv", xlsx: "/imports/s1/export?format=xlsx" },
    rejected: { csv: "/imports/s1/rejected?format=csv", xlsx: "/imports/s1/rejected?format=xlsx" },
  };

  it("says what approving does, with the counts, before asking for the signature", async () => {
    const onApprove = vi.fn();
    renderWithI18n(<ApprovePanel totals={previewPage().totals} approved={false} busy={false} links={links} onApprove={onApprove} />);
    expect(screen.getByText(/5 products will be saved/)).toBeInTheDocument();
    expect(screen.getByText(/1 rejected row stays out/)).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Approve and generate file" }));
    expect(onApprove).toHaveBeenCalled();
  });

  it("offers every download once approved", () => {
    renderWithI18n(<ApprovePanel totals={previewPage().totals} approved busy={false} links={links} onApprove={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "Approve and generate file" })).toBeNull();
    expect(screen.getByRole("link", { name: "Products (CSV)" })).toHaveAttribute("href", links.products.csv);
    expect(screen.getByRole("link", { name: "Products (XLSX)" })).toHaveAttribute("href", links.products.xlsx);
    expect(screen.getByRole("link", { name: "Rejected rows (CSV)" })).toHaveAttribute("href", links.rejected.csv);
    expect(screen.getByRole("link", { name: "Rejected rows (XLSX)" })).toHaveAttribute("href", links.rejected.xlsx);
  });

  it("names each file once and offers its formats as small keys beside it", () => {
    renderWithI18n(<ApprovePanel totals={previewPage().totals} approved busy={false} links={links} onApprove={vi.fn()} />);
    const downloads = screen.getByRole("list", { name: "Downloads" });
    const [products, rejected] = within(downloads).getAllByRole("listitem");
    expect(within(products).getByText("Products")).toBeInTheDocument();
    expect(within(products).getAllByRole("link").map((link) => link.textContent)).toEqual(["XLSX", "CSV"]);
    expect(within(rejected).getByText("Rejected rows")).toBeInTheDocument();
    expect(within(rejected).getAllByRole("link").map((link) => link.textContent)).toEqual(["XLSX", "CSV"]);
  });

  it("shows the first rows of the exported products file exactly as it was written", () => {
    const sheet = { header: ["supplier_code", "description", "unit_cost_net"], rows: [["A1", "Bolt, 6 mm", "1000.00"], ["B2", "Nut", "2420.00"]], total: 5 };
    renderWithI18n(<ApprovePanel totals={previewPage().totals} approved busy={false} links={links} sheets={{ products: sheet }} onApprove={vi.fn()} />);
    const table = screen.getByRole("table", { name: "The products file" });
    expect(within(table).getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual(sheet.header);
    expect(within(table).getByText("Bolt, 6 mm")).toBeInTheDocument();
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    expect(screen.getByText("First 2 of 5 rows")).toBeInTheDocument();
  });

  it("does not preview the file before the import is approved", () => {
    const sheet = { header: ["supplier_code"], rows: [["A1"]], total: 1 };
    renderWithI18n(<ApprovePanel totals={previewPage().totals} approved={false} busy={false} links={links} sheets={{ products: sheet, rejected: sheet }} onApprove={vi.fn()} />);
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("previews the rejected-rows file too, or says plainly that it is empty", () => {
    const products = { header: ["supplier_code"], rows: [["A1"]], total: 1 };
    const rejected = { header: ["source_row", "reasons", "Codigo"], rows: [["8", "cost: cannot parse 'abc'", "X9"]], total: 1 };
    const { unmount } = renderWithI18n(<ApprovePanel totals={previewPage().totals} approved busy={false} links={links} sheets={{ products, rejected }} onApprove={vi.fn()} />);
    const table = screen.getByRole("table", { name: "The rejected-rows file" });
    expect(within(table).getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual(rejected.header);
    expect(within(table).getByText("cost: cannot parse 'abc'")).toBeInTheDocument();
    unmount();
    renderWithI18n(<ApprovePanel totals={previewPage().totals} approved busy={false} links={links} sheets={{ products, rejected: { header: ["source_row", "reasons"], rows: [], total: 0 } }} onApprove={vi.fn()} />);
    expect(screen.queryByRole("table", { name: "The rejected-rows file" })).toBeNull();
    expect(screen.getByText("No rows were rejected.")).toBeInTheDocument();
  });
});

describe("waiting keys", () => {
  it("animates only the key that started the wait", async () => {
    const candidates = [{ row_index: 0, file_row: 1, cells: ["code", "price"] }, { row_index: 1, file_row: 2, cells: ["A1", "100"] }];
    const { rerender } = renderWithI18n(<HeaderChoice candidates={candidates} busy={false} onChoose={vi.fn()} />);
    const noHeader = screen.getAllByRole("button").at(-1)!;
    await userEvent.click(noHeader);
    rerender(<HeaderChoice candidates={candidates} busy onChoose={vi.fn()} />);
    const busyKeys = screen.getAllByRole("button").filter((key) => key.getAttribute("aria-busy") === "true");
    expect(busyKeys).toHaveLength(1);
    expect(busyKeys[0].textContent).toBe(noHeader.textContent);
  });

  it("animates the signature key while the import is being approved", async () => {
    const links = { products: { csv: "", xlsx: "" }, rejected: { csv: "", xlsx: "" } };
    const { rerender } = renderWithI18n(<ApprovePanel totals={previewPage().totals} approved={false} busy={false} links={links} onApprove={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Approve and generate file" }));
    rerender(<ApprovePanel totals={previewPage().totals} approved={false} busy links={links} onApprove={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Approve and generate file" })).toHaveAttribute("aria-busy", "true");
  });
});

describe("ErrorBanner", () => {
  it("says what went wrong in Spanish instead of the server's English message", () => {
    renderWithI18n(<ErrorBanner error={new ApiError(404, "session_not_found", "session 's1' does not exist")} />, "es");
    expect(screen.getByRole("alert")).toHaveTextContent("Esta importación ya no existe. Empiece una nueva.");
  });

  it("renders nothing without an error", () => {
    renderWithI18n(<ErrorBanner error={null} />);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("explains no_accepted_rows in plain words", () => {
    renderWithI18n(<ErrorBanner error={new ApiError(409, "no_accepted_rows", "nothing")} />);
    expect(screen.getByRole("alert")).toHaveTextContent("No row passed the checks");
  });

  it("falls back to the server message for an unknown code", () => {
    renderWithI18n(<ErrorBanner error={new ApiError(422, "unreadable_file", "The sheet is password protected")} />);
    expect(screen.getByRole("alert")).toHaveTextContent("The sheet is password protected");
  });

  it("explains an unreachable server", () => {
    renderWithI18n(<ErrorBanner error={new ApiError(0, "network_error", "x")} />);
    expect(screen.getByRole("alert")).toHaveTextContent("cannot be reached");
  });
});

describe("Stepper", () => {
  const steps: StepItem[] = [
    { id: "upload", state: "done" },
    { id: "columns", state: "current" },
    { id: "preview", state: "upcoming" },
  ];

  it("marks the current step and lets the user go back to finished ones only", async () => {
    const onSelect = vi.fn();
    renderWithI18n(<Stepper steps={steps} onSelect={onSelect} />);
    expect(screen.getByText("Columns").closest("li")).toHaveAttribute("aria-current", "step");
    expect(screen.getByRole("button", { name: /Upload/ })).toBeEnabled();
    expect(screen.queryByRole("button", { name: /Preview/ })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /Upload/ }));
    expect(onSelect).toHaveBeenCalledWith("upload");
  });

  it("shows a locked finished step as read-only instead of a link back", () => {
    renderWithI18n(
      <Stepper
        steps={[{ id: "upload", state: "done" }, { id: "columns", state: "done", locked: true }, { id: "approve", state: "current" }]}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: /Columns/ })).toBeNull();
    const locked = screen.getByText("Columns").closest("li")!;
    expect(locked).toHaveTextContent("locked");
    expect(locked).toHaveAttribute("title", "The import is approved, so this step can no longer change.");
    expect(screen.getByRole("button", { name: /Upload/ })).toBeEnabled();
  });
});

describe("LanguageToggle", () => {
  it("switches the interface language", async () => {
    renderWithI18n(<LanguageToggle />);
    expect(screen.getByRole("button", { name: "EN" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(screen.getByRole("button", { name: "ES" }));
    expect(screen.getByRole("button", { name: "ES" })).toHaveAttribute("aria-pressed", "true");
    expect(document.documentElement.lang).toBe("es");
  });

  it("stores the user choice in localStorage", async () => {
    localStorage.clear();
    renderWithI18n(<LanguageToggle />);
    await userEvent.click(screen.getByRole("button", { name: "ES" }));
    expect(localStorage.getItem("pricor.language")).toBe("es");
    await userEvent.click(screen.getByRole("button", { name: "EN" }));
    expect(localStorage.getItem("pricor.language")).toBe("en");
  });
});
