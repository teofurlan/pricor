import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import type { FxState, Language, PreviewFilter, PreviewItem, PreviewPage, PreviewStatusFilter } from "../../api/types";
import { useI18n } from "../../i18n";
import { conversionText, formatDecimalText, formatFigure, formatInteger } from "../../lib/decimalText";
import { Badge } from "../atoms/Badge";
import { Button } from "../atoms/Button";
import { StepTrace, visibleSteps } from "../molecules/StepTrace";
import { usePendingAction } from "../atoms/usePendingAction";

const DEFAULT_FILTER: PreviewFilter = { query: "", status: "all" };
const STATUS_OPTIONS: readonly PreviewStatusFilter[] = ["all", "accepted", "rejected"];
const SEARCH_DEBOUNCE_MS = 200;

interface Props {
  page: PreviewPage;
  busy: boolean;
  onPage(offset: number): void;
  fx?: FxState | null;
  filter?: PreviewFilter;
  onFilter?(next: PreviewFilter): void;
}

/** The accessible hint of a converted cell: the unrounded input and the rate behind the figure. */
function conversionTitle(item: PreviewItem, to: string, language: Language): string | undefined {
  const step = item.trace.find((entry) => entry.step === "convert_currency");
  const currency = item.record?.currency;
  if (!step || step.source === undefined || step.rate === undefined || !currency) return undefined;
  return conversionText({ source: step.source, rate: step.rate, value: step.value }, currency, to, language);
}

/** The ruled journal keeps every row; the selected row feeds the adjacent tape. */
export function PreviewTable({ page, busy, onPage, fx = null, filter = DEFAULT_FILTER, onFilter }: Props) {
  const { t, language } = useI18n();
  const pending = usePendingAction<"previous" | "next">(busy);
  const [selection, setSelection] = useState({ offset: page.offset, row: page.items[0]?.row_number });
  // Only the first trace is printed line by line; once the user browses, results appear at once.
  const [browsed, setBrowsed] = useState(false);
  const [draftQuery, setDraftQuery] = useState(filter.query);
  const debounceRef = useRef<number | null>(null);
  const tableRef = useRef<HTMLTableElement>(null);
  const helpId = useId();
  const searchId = useId();
  const selected = (selection.offset === page.offset && page.items.find((row) => row.row_number === selection.row)) || page.items[0];
  const first = page.items.length === 0 ? 0 : page.offset + 1;
  const last = page.offset + page.items.length;
  const filtered = filter.query.trim() !== "" || filter.status !== "all";
  const vatStripped = page.items.some((item) =>
    visibleSteps(item.trace, item.record?.currency ?? null, fx?.to ?? null).shown.some((step) => step.step === "strip_vat"),
  );

  useEffect(() => {
    setDraftQuery(filter.query);
  }, [filter.query]);

  useEffect(() => () => {
    if (debounceRef.current !== null) window.clearTimeout(debounceRef.current);
  }, []);

  function commitFilter(next: PreviewFilter) {
    if (debounceRef.current !== null) {
      window.clearTimeout(debounceRef.current);
      debounceRef.current = null;
    }
    setBrowsed(true);
    onFilter?.(next);
  }

  function handleQueryChange(value: string) {
    setDraftQuery(value);
    if (!onFilter) return;
    if (debounceRef.current !== null) window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => {
      debounceRef.current = null;
      setBrowsed(true);
      onFilter({ query: value, status: filter.status });
    }, SEARCH_DEBOUNCE_MS);
  }

  function handleSearchSubmit(event: FormEvent) {
    event.preventDefault();
    commitFilter({ query: draftQuery, status: filter.status });
  }

  function clearFilters() {
    setDraftQuery("");
    commitFilter(DEFAULT_FILTER);
  }

  function select(row: number) {
    setBrowsed(true);
    setSelection({ offset: page.offset, row });
  }

  function turnPage(offset: number) {
    setBrowsed(true);
    onPage(offset);
  }

  function move(event: KeyboardEvent) {
    if (!selected || !["ArrowUp", "ArrowDown"].includes(event.key)) return;
    event.preventDefault();
    const index = page.items.indexOf(selected);
    const next = Math.max(0, Math.min(page.items.length - 1, index + (event.key === "ArrowDown" ? 1 : -1)));
    select(page.items[next].row_number);
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
          {onFilter && (
            <form className="filter-bar" role="search" onSubmit={handleSearchSubmit}>
              <div className="filter-bar__search">
                <label className="sr-only" htmlFor={searchId}>{t("preview.search.label")}</label>
                <input
                  id={searchId}
                  type="search"
                  value={draftQuery}
                  placeholder={t("preview.search.placeholder")}
                  autoComplete="off"
                  onChange={(event) => handleQueryChange(event.target.value)}
                />
              </div>
              <div className="filter-keys" role="group" aria-label={t("preview.filter.label")}>
                {STATUS_OPTIONS.map((option) => (
                  <button
                    key={option}
                    type="button"
                    className="button lang__option"
                    aria-pressed={filter.status === option}
                    onClick={() => commitFilter({ query: draftQuery, status: option })}
                  >
                    {t(`preview.filter.${option}`)}
                  </button>
                ))}
              </div>
              {(filtered || draftQuery.trim() !== "") && (
                <Button variant="quiet" onClick={clearFilters}>{t("preview.filter.clear")}</Button>
              )}
            </form>
          )}
          <div className="table-wrap preview-journal__rows" role="region" aria-label={t("preview.rows")} tabIndex={0} aria-describedby={helpId} aria-busy={busy} onKeyDown={move}>
            <table ref={tableRef} className="table table--preview">
              <thead>
                <tr>
                  <th scope="col"># {t("preview.row")}</th>
                  <th scope="col">{t("report.col.code")}</th>
                  <th scope="col">{t("report.col.description")}</th>
                  <th scope="col" className="num">{t(vatStripped ? "trace.rounding.exVat" : "trace.rounding")}</th>
                  {fx && <th scope="col" className="num">{t("preview.converted", { currency: fx.to })}</th>}
                </tr>
              </thead>
              <tbody>
                {page.items.map((item) => (
                  <tr
                    key={item.row_number}
                    className={`${item.status === "rejected" ? "row--rejected" : ""}${selected === item ? " row--selected" : ""}`.trim()}
                    onClick={() => select(item.row_number)}
                  >
                    <th scope="row" className="cell--row">
                      <button type="button" className="row-key" aria-label={t("preview.rowNumber", { row: item.row_number })} aria-pressed={selected === item} onClick={() => select(item.row_number)}>{item.row_number}</button>
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
                      {item.record?.unit_cost_net ? <><span>{formatDecimalText(item.record.unit_cost_net, language)}</span><small>{item.record.currency}</small></> : "—"}
                    </td>
                    {fx && <td className="num cell--converted" title={conversionTitle(item, fx.to, language)}>{item.record?.unit_cost_net_converted ? formatFigure(`${item.record.unit_cost_net_converted} ${fx.to}`, language) : "—"}</td>}
                  </tr>
                ))}
              </tbody>
            </table>
            {page.items.length === 0 && (
              <div className="empty-state">
                <p>{t(filtered ? "preview.filter.empty" : "preview.empty")}</p>
                {filtered && onFilter && (
                  <div className="actions"><Button variant="quiet" onClick={clearFilters}>{t("preview.filter.clear")}</Button></div>
                )}
              </div>
            )}
          </div>
          <div className="pager">
            <span>{t("preview.range", { first: formatInteger(first, language), last: formatInteger(last, language), total: formatInteger(page.total_items, language) })}</span>
            <div className="actions">
              <Button disabled={busy || page.offset === 0} loading={pending.isLoading("previous")} onClick={() => { pending.mark("previous"); turnPage(Math.max(0, page.offset - page.limit)); }}>{t("preview.previous")}</Button>
              <Button disabled={busy || last >= page.total_items} loading={pending.isLoading("next")} onClick={() => { pending.mark("next"); turnPage(page.offset + page.limit); }}>{t("preview.next")}</Button>
            </div>
          </div>
        </div>
        <section className="tape tape--sticky" aria-label={t("preview.steps")}>
          <h2 className="tape__heading">{t("preview.steps")}</h2>
          {selected ? <>
            <p className="tape__reference"># {t("preview.rowNumber", { row: selected.row_number })}{selected.record?.supplier_code ? ` / ${selected.record.supplier_code}` : ""}</p>
            {selected.record?.description && <p className="tape__description">{selected.record.description}</p>}
            {selected.status === "rejected" ? <div className="reasons"><strong>{t("preview.rejected")}</strong>{selected.reasons.map((reason) => <p key={reason}>{reason}</p>)}</div> : selected.trace.length ? <StepTrace key={selected.row_number} trace={selected.trace} currency={selected.record?.currency ?? null} convertedCurrency={fx?.to ?? null} animate={!browsed} announce /> : <p className="hint">{t("preview.noTrace")}</p>}
          </> : <p className="hint">{t("preview.empty")}</p>}
        </section>
      </div>
    </div>
  );
}
