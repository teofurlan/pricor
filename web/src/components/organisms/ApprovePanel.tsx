import { useId } from "react";
import type { ExportFile, ExportSheet } from "../../api/client";
import type { PreviewTotals } from "../../api/types";
import { useI18n } from "../../i18n";
import { Button } from "../atoms/Button";
import { CountsSummary } from "../molecules/CountsSummary";
import { usePendingAction } from "../atoms/usePendingAction";

export interface DownloadLinks {
  products: { csv: string; xlsx: string };
  rejected: { csv: string; xlsx: string };
}

interface Props {
  totals: PreviewTotals;
  approved: boolean;
  busy: boolean;
  links: DownloadLinks;
  supplier?: string;
  file?: string;
  /** The approved files as written; shown only after approval. */
  sheets?: Partial<Record<ExportFile, ExportSheet | null>>;
  onApprove(): void;
}

/** The signature and its receipts share the exact counts that were previewed. */
export function ApprovePanel({ totals, approved, busy, links, supplier, file, sheets = {}, onApprove }: Props) {
  const { t } = useI18n();
  const pending = usePendingAction<"approve">(busy);
  return (
    <div className="stack">
      <div className="workbench workbench--approval">
        <div className="sign">
          <p className="sign__statement">
            {approved ? t("approve.done", { count: totals.accepted }) : <>
              {t(totals.accepted === 1 ? "approve.statement.one" : "approve.statement.other", { count: totals.accepted })}{" "}
              {t(totals.rejected === 1 ? "approve.rejected.one" : "approve.rejected.other", { count: totals.rejected })}
            </>}
          </p>
          {approved && <ul className="downloads" aria-label={t("approve.downloads")}>
            <li className="download">
              <span className="download__name">{t("approve.products")}</span>
              <a className="download__format" href={links.products.xlsx} download aria-label={t("approve.productsXlsx")}>XLSX</a>
              <a className="download__format" href={links.products.csv} download aria-label={t("approve.productsCsv")}>CSV</a>
            </li>
            <li className="download">
              <span className="download__name">{t("approve.rejectedRows")}</span>
              <a className="download__format" href={links.rejected.xlsx} download aria-label={t("approve.rejectedXlsx")}>XLSX</a>
              <a className="download__format" href={links.rejected.csv} download aria-label={t("approve.rejectedCsv")}>CSV</a>
            </li>
          </ul>}
        </div>
        <section className="tape tape--sticky tape--approval" aria-label={t("title.approve")}>
          <h2 className="tape__heading">{t("title.approve")}</h2>
          {supplier && <p className="tape__reference"># {t("session.supplier")} / {supplier}</p>}
          {file && <p className="tape__reference"># {t("session.file")} / {file}</p>}
          <CountsSummary totals={totals} tape />
          {!approved && <Button variant="primary" className="button--sign" disabled={busy} loading={pending.isLoading("approve")} onClick={() => { pending.mark("approve"); onApprove(); }}>{t("approve.button")}<span aria-hidden="true"> =</span></Button>}
          <div className="tape__tear" aria-hidden="true" />
        </section>
      </div>
      {approved && sheets.products && sheets.products.header.length > 0 && <SheetPreview sheet={sheets.products} file="products" />}
      {approved && sheets.rejected && sheets.rejected.header.length > 0 && <SheetPreview sheet={sheets.rejected} file="rejected" />}
    </div>
  );
}

/** The first rows of one exported file, cell for cell as the download contains them. */
function SheetPreview({ sheet, file }: { sheet: ExportSheet; file: ExportFile }) {
  const { t } = useI18n();
  const titleId = useId();
  return (
    <section className="output-sheet stack" aria-labelledby={titleId}>
      <div>
        <h2 className="subtitle" id={titleId}>{t(file === "products" ? "approve.sheetTitle" : "approve.rejectedSheetTitle")}</h2>
        {sheet.total > 0 && <p className="hint">{t("approve.sheetHint")} <span>{t("approve.sheetRange", { shown: sheet.rows.length, total: sheet.total })}</span></p>}
      </div>
      {sheet.total === 0 ? (
        <p className="empty-state">{t("rejected.none")}</p>
      ) : (
        <div className="table-wrap">
          <table className="table table--sheet" aria-labelledby={titleId}>
            <thead>
              <tr>{sheet.header.map((name, column) => <th key={column} scope="col">{name}</th>)}</tr>
            </thead>
            <tbody>
              {sheet.rows.map((row, index) => (
                <tr key={index}>{sheet.header.map((_, column) => <td key={column}>{row[column] ?? ""}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
