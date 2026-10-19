import { fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import { column, previewItem, previewPage, question } from "../../test/fixtures";
import { renderWithI18n } from "../../test/render";
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
  it("cannot start until there is a supplier name and a file", async () => {
    renderWithI18n(<UploadForm busy={false} onSubmit={vi.fn()} />);
    const start = screen.getByRole("button", { name: "Start import" });
    expect(start).toBeDisabled();

    await userEvent.type(screen.getByLabelText("Supplier name"), "Ferreteria Ejemplo");
    expect(start).toBeDisabled();

    await userEvent.upload(screen.getByLabelText("Price list file"), new File(["a"], "lista.csv"));
    expect(start).toBeEnabled();
  });

  it("submits the supplier, file, optional sheet and language for a multi-sheet file", async () => {
    const onSubmit = vi.fn();
    const onInspectSheets = vi.fn().mockResolvedValue(["Hoja 1", "Hoja 2"]);
    renderWithI18n(<UploadForm busy={false} onSubmit={onSubmit} onInspectSheets={onInspectSheets} />);
    const file = new File(["a"], "catalogo.xlsx");
    await userEvent.type(screen.getByLabelText("Supplier name"), "Acme");
    await userEvent.upload(screen.getByLabelText("Price list file"), file);

    // Sheet select should appear once multi-sheet file is inspected
    const sheetSelect = await screen.findByLabelText("Sheet");
    expect(sheetSelect).toBeInTheDocument();
    expect(sheetSelect).toHaveValue("");
    expect(within(sheetSelect).getByRole("option", { name: "First sheet with data" })).toHaveValue("");

    await userEvent.selectOptions(sheetSelect, "Hoja 2");
    await userEvent.selectOptions(screen.getByLabelText("Language of the questions"), "es");
    await userEvent.click(screen.getByRole("button", { name: "Start import" }));

    expect(onSubmit).toHaveBeenCalledWith({ file, supplierName: "Acme", sheet: "Hoja 2", language: "es" });
  });

  it("hides the sheet select when the file has only one sheet or is single-sheet csv", async () => {
    const onSubmit = vi.fn();
    const onInspectSheets = vi.fn().mockResolvedValue(["lista_octubre"]);
    renderWithI18n(<UploadForm busy={false} onSubmit={onSubmit} onInspectSheets={onInspectSheets} />);
    const file = new File(["a"], "lista.csv");
    await userEvent.type(screen.getByLabelText("Supplier name"), "Acme");
    await userEvent.upload(screen.getByLabelText("Price list file"), file);

    // Give microtasks time to run
    expect(screen.queryByLabelText(/Sheet/i)).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Start import" }));
    expect(onSubmit).toHaveBeenCalledWith({ file, supplierName: "Acme", sheet: "", language: "en" });
  });

  it("renders drop zone copy and changes text on dragover", () => {
    renderWithI18n(<UploadForm busy={false} onSubmit={vi.fn()} />);
    const dropzone = document.querySelector(".dropzone");
    expect(dropzone).toBeInTheDocument();
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
    expect(within(dropzone as HTMLElement).getByText("Arrastrá tu lista de precios acá")).toBeInTheDocument();
    expect(within(dropzone as HTMLElement).getByText("o")).toBeInTheDocument();
    expect(within(dropzone as HTMLElement).getByText("Seleccionar archivo")).toBeInTheDocument();
    expect(within(dropzone as HTMLElement).getByText("Excel (.xls, .xlsx) o CSV · hasta 20 MB")).toBeInTheDocument();

    const file = new File(["col1,col2"], "test.csv", { type: "text/csv" });
    fireEvent.dragOver(dropzone!, { dataTransfer: { files: [file] } });
    expect(within(dropzone as HTMLElement).getByText("Soltala para leerla")).toBeInTheDocument();
  });

  it("shows file name in mono with its size and the Change file key when a file is selected", async () => {
    renderWithI18n(<UploadForm busy={false} onSubmit={vi.fn()} />);
    const file = new File(["a".repeat(1536)], "precios-semana-42.csv", { type: "text/csv" });
    const input = screen.getByLabelText("Price list file");
    await userEvent.upload(input, file);

    const dropzone = document.querySelector(".dropzone") as HTMLElement;
    expect(within(dropzone).getByText(/precios-semana-42\.csv/)).toBeInTheDocument();
    expect(within(dropzone).getByText(/1\.5 KB/)).toBeInTheDocument();
    expect(within(dropzone).getByRole("button", { name: "Change file" })).toBeInTheDocument();
    expect(dropzone.querySelector(".feed-slit")).not.toBeInTheDocument();
  });

  it("handles drag and drop with dragover state and accepts only one file", async () => {
    const onSubmit = vi.fn();
    renderWithI18n(<UploadForm busy={false} onSubmit={onSubmit} />);
    const dropzone = document.querySelector(".dropzone");
    expect(dropzone).toBeInTheDocument();
    expect(dropzone).not.toHaveClass("dropzone--active");

    const file1 = new File(["1"], "primero.csv", { type: "text/csv" });
    const file2 = new File(["2"], "segundo.csv", { type: "text/csv" });

    // Drag over
    fireEvent.dragOver(dropzone!, { dataTransfer: { files: [file1] } });
    expect(dropzone).toHaveClass("dropzone--active");

    // Drag leave
    fireEvent.dragLeave(dropzone!);
    expect(dropzone).not.toHaveClass("dropzone--active");

    // Drag over and drop multiple files
    fireEvent.dragOver(dropzone!, { dataTransfer: { files: [file1, file2] } });
    fireEvent.drop(dropzone!, { dataTransfer: { files: [file1, file2] } });

    expect(dropzone).not.toHaveClass("dropzone--active");
    // Only file1 is accepted
    expect(screen.getByText(/primero\.csv/)).toBeInTheDocument();
    expect(screen.queryByText(/segundo\.csv/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Change file" })).toBeInTheDocument();

    // Native input remains accessible
    expect(screen.getByLabelText("Price list file")).toBeInTheDocument();
  });

  it("can ask to ignore the saved plan and start from scratch", async () => {
    const onSubmit = vi.fn();
    renderWithI18n(<UploadForm busy={false} onSubmit={onSubmit} />);
    const fresh = "Start from scratch instead of reusing the saved plan";
    await userEvent.type(screen.getByLabelText("Supplier name"), "Acme");
    await userEvent.upload(screen.getByLabelText("Price list file"), new File(["a"], "lista.csv"));
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
    await screen.findByLabelText("Sheet");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
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
    expect(within(rowCodigo).getByText("✓ Set by the model (confident)")).toBeInTheDocument();

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
    expect(screen.getByRole("columnheader", { name: "Suggestion (model confidence)" })).toBeInTheDocument();

    // Suggested role uses role.* label: "Product code" (not raw "CODE")
    const suggestionCell = row.querySelector(".cell--suggestion") as HTMLElement;
    expect(within(suggestionCell).getByText("Product code")).toBeInTheDocument();

    // No raw .98 text
    expect(within(row).queryByText(".98")).not.toBeInTheDocument();
    expect(within(row).queryByText("0.98")).not.toBeInTheDocument();

    // 5-segment meter with sage level class
    const meter = within(row).getByRole("meter");
    expect(meter).toHaveAttribute("aria-label", "Model confidence 98 %, proposed by Laya");
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
    expect(meter0).toHaveAttribute("aria-label", "Model confidence 98 %, proposed by Laya");
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
    expect(within(row0).getByRole("button", { name: /Change/i })).toBeInTheDocument();

    // Row 1 (suggestion is "ignore"): only [✓ Accept] and [Change ▾], NO duplicate Ignore button
    const row1 = screen.getByRole("row", { name: /ColB/ });
    expect(within(row1).getByRole("button", { name: /Accept/i })).toBeInTheDocument();
    expect(within(row1).queryByRole("button", { name: /Ignore/i })).not.toBeInTheDocument();
    expect(within(row1).getByRole("button", { name: /Change/i })).toBeInTheDocument();

    // Row 2 (no suggestion): [⊘ Ignore] and [Change ▾], NO Accept button
    const row2 = screen.getByRole("row", { name: /ColC/ });
    expect(within(row2).queryByRole("button", { name: /Accept/i })).not.toBeInTheDocument();
    expect(within(row2).getByRole("button", { name: /Ignore/i })).toBeInTheDocument();
    expect(within(row2).getByRole("button", { name: /Change/i })).toBeInTheDocument();
  });

  it("allows picking a role, shows chosen role with Back to suggestion, and Back to suggestion clears choice", async () => {
    renderWithI18n(<ColumnsTable columns={columns} issues={[]} busy={false} onConfirm={vi.fn()} />);
    const row = screen.getByRole("row", { name: /Misterio/ });

    // Click Change to reveal role select
    await userEvent.click(within(row).getByRole("button", { name: /Change/i }));
    const select = within(row).getByRole("combobox");
    expect(select).toBeInTheDocument();

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

    // Update live before saving: click Change on Column 1 and pick Description
    const rowDesc = within(document.querySelector(".table--columns") as HTMLElement).getByRole("row", { name: /Descripcion/ });
    await userEvent.click(within(rowDesc).getByRole("button", { name: /Change/i }));
    await userEvent.selectOptions(within(rowDesc).getByRole("combobox"), "description");

    // Header in preview table updates live to "Description" and loses muted ink
    expect(within(previewTable).getByText("Description")).not.toHaveClass("preview-th--muted");
  });
});

describe("QuestionsPanel", () => {
  it("renders one card per open question and waits for the answers", () => {
    renderWithI18n(
      <QuestionsPanel
        questions={[question(), question({ id: "price_includes_vat", text: { en: "Include VAT?", es: "¿Incluye IVA?" } })]}
        answers={{}}
        busy={false}
        onAnswer={vi.fn()}
        onContinue={vi.fn()}
      />,
    );
    expect(screen.getAllByRole("group")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "See the preview" })).toBeDisabled();
  });

  it("keeps answered questions on screen, changeable, and lets the user continue once none is open", async () => {
    const onContinue = vi.fn();
    const onAnswer = vi.fn();
    renderWithI18n(
      <QuestionsPanel questions={[question()]} answers={{ currency: "ARS" }} busy={false} onAnswer={onAnswer} onContinue={onContinue} />,
    );
    expect(screen.getByRole("radio", { name: /Argentine pesos/ })).toBeChecked();
    await userEvent.click(screen.getByRole("radio", { name: /US dollars/ }));
    expect(onAnswer).toHaveBeenCalledWith("currency", "USD");
    await userEvent.click(screen.getByRole("button", { name: "See the preview" }));
    expect(onContinue).toHaveBeenCalled();
  });

  it("says so when there is nothing to ask", () => {
    renderWithI18n(<QuestionsPanel questions={[]} answers={{}} busy={false} onAnswer={vi.fn()} onContinue={vi.fn()} />);
    expect(screen.getByText("Every question is answered.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "See the preview" })).toBeEnabled();
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
  it("shows the file row and original cells in the journal, with every step and final cost on the selected tape", async () => {
    renderWithI18n(<PreviewTable page={previewPage()} busy={false} onPage={vi.fn()} />);
    const row = screen.getByRole("button", { name: "Row 3" }).closest("tr")!;
    await userEvent.click(within(row).getByText("In your file"));
    expect(within(row).getByText("A1, Tornillo, 1.210,00, 21%")).toBeVisible();
    const tape = screen.getByRole("region", { name: "From file to cost" });
    expect(await within(tape).findByText("VAT removed")).toBeInTheDocument();
    expect(await within(tape).findByText("1000.00 ARS")).toBeInTheDocument();
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
    await userEvent.click(screen.getByRole("button", { name: "Approve import" }));
    expect(onApprove).toHaveBeenCalled();
  });

  it("offers every download once approved", () => {
    renderWithI18n(<ApprovePanel totals={previewPage().totals} approved busy={false} links={links} onApprove={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "Approve import" })).toBeNull();
    expect(screen.getByRole("link", { name: "Products (CSV)" })).toHaveAttribute("href", links.products.csv);
    expect(screen.getByRole("link", { name: "Products (XLSX)" })).toHaveAttribute("href", links.products.xlsx);
    expect(screen.getByRole("link", { name: "Rejected rows (CSV)" })).toHaveAttribute("href", links.rejected.csv);
    expect(screen.getByRole("link", { name: "Rejected rows (XLSX)" })).toHaveAttribute("href", links.rejected.xlsx);
  });
});

describe("ErrorBanner", () => {
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
});

describe("LanguageToggle", () => {
  it("switches the interface language", async () => {
    renderWithI18n(<LanguageToggle />);
    expect(screen.getByRole("button", { name: "EN" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(screen.getByRole("button", { name: "ES" }));
    expect(screen.getByRole("button", { name: "ES" })).toHaveAttribute("aria-pressed", "true");
    expect(document.documentElement.lang).toBe("es");
  });
});
