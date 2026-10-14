import { screen, within } from "@testing-library/react";
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

  it("submits the supplier, file, optional sheet and language", async () => {
    const onSubmit = vi.fn();
    renderWithI18n(<UploadForm busy={false} onSubmit={onSubmit} />);
    const file = new File(["a"], "lista.csv");
    await userEvent.type(screen.getByLabelText("Supplier name"), "Acme");
    await userEvent.upload(screen.getByLabelText("Price list file"), file);
    await userEvent.type(screen.getByLabelText("Sheet (optional)"), "Hoja1");
    await userEvent.selectOptions(screen.getByLabelText("Language of the questions"), "es");
    await userEvent.click(screen.getByRole("button", { name: "Start import" }));

    expect(onSubmit).toHaveBeenCalledWith({ file, supplierName: "Acme", sheet: "Hoja1", language: "es" });
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
    column({ index: 0, header: "Codigo", role: "code", decided_by: "heuristics", samples: ["A1", "A2"] }),
    column({ index: 1, header: "Precio", role: "cost_price", decided_by: "gemma", score: 0.7, rationale: "looks like a price" }),
    column({ index: 2, header: "Misterio", role: null, decided_by: null, score: 0.2, samples: ["x"] }),
  ];

  it("shows header, samples, role, who decided, score and rationale", () => {
    renderWithI18n(<ColumnsTable columns={columns} issues={[]} busy={false} onConfirm={vi.fn()} />);
    const row = screen.getByRole("row", { name: /Precio/ });
    expect(within(row).getByText("Gemma")).toBeInTheDocument();
    expect(within(row).getByText("0.7")).toBeInTheDocument();
    expect(within(row).getByText("looks like a price")).toBeInTheDocument();
    expect(within(row).getByRole("combobox")).toHaveValue("cost_price");
    expect(within(screen.getByRole("row", { name: /Codigo/ })).getByText("A1, A2")).toBeInTheDocument();
  });

  it("highlights the columns that need the user and blocks confirming until they are set", async () => {
    const onConfirm = vi.fn();
    renderWithI18n(<ColumnsTable columns={columns} issues={[]} busy={false} onConfirm={onConfirm} />);
    const row = screen.getByRole("row", { name: /Misterio/ });
    expect(row).toHaveClass("row--attention");
    expect(within(row).getByText("Needs your choice")).toBeInTheDocument();
    const confirm = screen.getByRole("button", { name: "Confirm columns" });
    expect(confirm).toBeDisabled();

    await userEvent.selectOptions(within(row).getByRole("combobox"), "barcode");
    expect(within(row).getByText("You")).toBeInTheDocument();
    expect(confirm).toBeEnabled();
    await userEvent.click(confirm);
    expect(onConfirm).toHaveBeenCalledWith({ 2: "barcode" });
  });

  it("sends only the corrections, so confirming untouched columns changes nothing", async () => {
    const onConfirm = vi.fn();
    renderWithI18n(<ColumnsTable columns={columns.slice(0, 2)} issues={[]} busy={false} onConfirm={onConfirm} />);
    await userEvent.click(screen.getByRole("button", { name: "Confirm columns" }));
    expect(onConfirm).toHaveBeenCalledWith({});
  });

  it("lists role issues from the server", () => {
    renderWithI18n(
      <ColumnsTable columns={columns.slice(0, 1)} issues={["no column is marked as the cost"]} busy={false} onConfirm={vi.fn()} />,
    );
    expect(screen.getByText("no column is marked as the cost")).toBeInTheDocument();
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
});

describe("PreviewTable", () => {
  it("shows the file row, the original cells, every step and the final cost with its currency", () => {
    renderWithI18n(<PreviewTable page={previewPage()} busy={false} onPage={vi.fn()} />);
    const row = screen.getByRole("row", { name: /Row 3/ });
    expect(within(row).getByText("A1, Tornillo, 1.210,00, 21%")).toBeInTheDocument();
    expect(within(row).getByText("VAT removed")).toBeInTheDocument();
    expect(within(row).getByText("1000.00 ARS")).toBeInTheDocument();
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
    const row = screen.getByRole("row", { name: /Row 8/ });
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
