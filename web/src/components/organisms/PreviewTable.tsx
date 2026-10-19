import { useId, useRef, useState, type KeyboardEvent } from "react";
import type { FxState, PreviewPage } from "../../api/types";
import { useI18n } from "../../i18n";
import { Badge } from "../atoms/Badge";
import { Button } from "../atoms/Button";
import { StepTrace } from "../molecules/StepTrace";

interface Props {
  page: PreviewPage;
  busy: boolean;
  onPage(offset: number): void;
  fx?: FxState | null;
}

/** The ruled journal keeps every row; the selected row feeds the adjacent tape. */
export function PreviewTable({ page, busy, onPage, fx = null }: Props) {
  const { t } = useI18n();
  const [selection, setSelection] = useState({ offset: page.offset, row: page.items[0]?.row_number });
  const tableRef = useRef<HTMLTableElement>(null);
  const helpId = useId();
  const selected = (selection.offset === page.offset && page.items.find((row) => row.row_number === selection.row)) || page.items[0];
  const first = page.items.length === 0 ? 0 : page.offset + 1;
  const last = page.offset + page.items.length;

  function move(event: KeyboardEvent) {
    if (!selected || !["ArrowUp", "ArrowDown"].includes(event.key)) return;
    event.preventDefault();
    const index = page.items.indexOf(selected);
    const next = Math.max(0, Math.min(page.items.length - 1, index + (event.key === "ArrowDown" ? 1 : -1)));
    setSelection({ offset: page.offset, row: page.items[next].row_number });
    const row = tableRef.current?.tBodies[0]?.rows[next];
    row?.scrollIntoView?.({ block: "nearest" });
    // When navigation starts on a row key, keep keyboard focus with that row.
    if (event.target instanceof HTMLButtonElement) row?.querySelector("button")?.focus({ preventScroll: true });
  }

  return (
    <div className="stack">
      <p className="hint" id={helpId}>{t("preview.keyboard")}</p>
      <div className="workbench workbench--preview">
        <div className="preview-journal">
          <div className="table-wrap preview-journal__rows" role="region" aria-label={t("preview.rows")} tabIndex={0} aria-describedby={helpId} aria-busy={busy} onKeyDown={move}>
            <table ref={tableRef} className="table table--preview">
              <thead>
                <tr>
                  <th scope="col"># {t("preview.row")}</th>
                  <th scope="col">{t("report.col.code")}</th>
                  <th scope="col">{t("report.col.description")}</th>
                  <th scope="col" className="num">{t("trace.rounding")}</th>
                  {fx && <th scope="col" className="num">{t("preview.converted", { currency: fx.to })}</th>}
                </tr>
              </thead>
              <tbody>
                {page.items.map((item) => (
                  <tr
                    key={item.row_number}
                    className={`${item.status === "rejected" ? "row--rejected" : ""}${selected === item ? " row--selected" : ""}`.trim()}
                    onClick={() => setSelection({ offset: page.offset, row: item.row_number })}
                  >
                    <th scope="row" className="cell--row">
                      <button type="button" className="row-key" aria-label={t("preview.rowNumber", { row: item.row_number })} aria-pressed={selected === item} onClick={() => setSelection({ offset: page.offset, row: item.row_number })}>{item.row_number}</button>
                    </th>
                    <td className="cell--code">{item.record?.supplier_code ?? "—"}</td>
                    <td>
                      {item.record?.description && <span className="cell__name">{item.record.description}</span>}
                      <details className="original-cells">
                        <summary>{t("preview.original")}</summary>
                        <p>{item.original.join(", ")}</p>
                      </details>
                      {item.status === "rejected" && <div className="reasons"><Badge tone="bad">{t("preview.rejected")}</Badge>{item.reasons.map((reason) => <p key={reason}>{reason}</p>)}</div>}
                    </td>
                    <td className="num cell--cost">
                      {item.record?.unit_cost_net ? <><span>{item.record.unit_cost_net}</span><small>{item.record.currency}</small></> : "—"}
                    </td>
                    {fx && <td className="num cell--converted">{item.record?.unit_cost_net_converted ? `${item.record.unit_cost_net_converted} ${fx.to}` : "—"}</td>}
                  </tr>
                ))}
              </tbody>
            </table>
            {page.items.length === 0 && <p className="empty-state">{t("preview.empty")}</p>}
          </div>
          <div className="pager">
            <span>{t("preview.range", { first, last, total: page.total_items })}</span>
            <div className="actions">
              <Button disabled={busy || page.offset === 0} onClick={() => onPage(Math.max(0, page.offset - page.limit))}>{t("preview.previous")}</Button>
              <Button disabled={busy || last >= page.total_items} onClick={() => onPage(page.offset + page.limit)}>{t("preview.next")}</Button>
            </div>
          </div>
        </div>
        <section className="tape tape--sticky" aria-label={t("preview.steps")}>
          <h2 className="tape__heading">{t("preview.steps")}</h2>
          {selected ? <>
            <p className="tape__reference"># {t("preview.rowNumber", { row: selected.row_number })}{selected.record?.supplier_code ? ` / ${selected.record.supplier_code}` : ""}</p>
            {selected.record?.description && <p className="tape__description">{selected.record.description}</p>}
            {selected.status === "rejected" ? <div className="reasons"><strong>{t("preview.rejected")}</strong>{selected.reasons.map((reason) => <p key={reason}>{reason}</p>)}</div> : selected.trace.length ? <StepTrace key={selected.row_number} trace={selected.trace} currency={selected.record?.currency ?? null} convertedCurrency={fx?.to ?? null} animate /> : <p className="hint">{t("preview.noTrace")}</p>}
          </> : <p className="hint">{t("preview.empty")}</p>}
        </section>
      </div>
    </div>
  );
}
