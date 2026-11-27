import { useEffect, useId, useState, type FormEvent } from "react";
import type { PreviewItem, ResolveRowsInput, ResolveRowsResult, RowContext } from "../../api/types";
import { useI18n } from "../../i18n";
import { formatInteger } from "../../lib/decimalText";
import { Button } from "../atoms/Button";

interface Props {
  item: PreviewItem;
  reasonCounts: Record<string, number>;
  readOnly?: boolean;
  revision?: string;
  onLoadRowContext?: (rowNumber: number) => Promise<RowContext>;
  onResolveRows?: (input: ResolveRowsInput) => Promise<ResolveRowsResult>;
}

/** Shows ±2 document rows around a rejected row and offers single or batch error resolution. */
export function RowErrorResolver({
  item,
  reasonCounts,
  readOnly = false,
  revision = "",
  onLoadRowContext,
  onResolveRows,
}: Props) {
  const { t, language } = useI18n();
  const [context, setContext] = useState<RowContext | null>(null);
  const [loadingContext, setLoadingContext] = useState(false);
  const [contextError, setContextError] = useState<string | null>(null);
  const [selectedColumn, setSelectedColumn] = useState<number>(0);
  const [draftValue, setDraftValue] = useState("");
  const [resolving, setResolving] = useState(false);
  const [resolveError, setResolveError] = useState<string | null>(null);
  const colSelectId = useId();
  const editInputId = useId();

  useEffect(() => {
    setResolveError(null);
    if (!onLoadRowContext) {
      setContext(null);
      setContextError(null);
      setLoadingContext(false);
      return;
    }
    let active = true;
    setLoadingContext(true);
    setContextError(null);
    onLoadRowContext(item.row_number)
      .then((loaded) => {
        if (!active) return;
        setContext(loaded);
        const initialCol = loaded.target_columns[0] ?? 0;
        setSelectedColumn(initialCol);
        const targetRow = loaded.rows.find((row) => row.is_target);
        setDraftValue(targetRow ? (targetRow.cells[initialCol] ?? "") : "");
      })
      .catch((failure: unknown) => {
        if (!active) return;
        setContext(null);
        setContextError(failure instanceof Error ? failure.message : String(failure));
      })
      .finally(() => {
        if (active) setLoadingContext(false);
      });
    return () => {
      active = false;
    };
  }, [item.row_number, onLoadRowContext, revision]);

  const primaryReason = item.reasons[0] ?? "";
  const reasonCount = primaryReason ? (reasonCounts[primaryReason] ?? 1) : 1;
  const formattedCount = formatInteger(reasonCount, language);
  const targetColumns = context?.target_columns ?? [];
  const activeHeader = context?.headers[selectedColumn] ?? "";
  const realColumnIndex = context?.column_indexes?.[selectedColumn] ?? selectedColumn;
  const editReason =
    (activeHeader && item.reasons.find((reason) => reason.startsWith(`${activeHeader}: `))) ||
    primaryReason;
  const editReasonCount = editReason ? (reasonCounts[editReason] ?? 1) : 1;
  const formattedEditCount = formatInteger(editReasonCount, language);

  function handleColumnChange(nextColumn: number) {
    setSelectedColumn(nextColumn);
    const targetRow = context?.rows.find((row) => row.is_target);
    setDraftValue(targetRow ? (targetRow.cells[nextColumn] ?? "") : "");
  }

  async function resolve(input: ResolveRowsInput) {
    if (!onResolveRows || resolving) return;
    setResolving(true);
    setResolveError(null);
    try {
      await onResolveRows(input);
    } catch (failure: unknown) {
      setResolveError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setResolving(false);
    }
  }

  function handleEditSubmit(event: FormEvent) {
    event.preventDefault();
    void resolve({
      action: "edit_cell",
      row_number: item.row_number,
      column_index: realColumnIndex,
      value: draftValue,
    });
  }

  return (
    <div className="row-resolver stack">
      {!onLoadRowContext && item.original.length > 0 && (
        <details className="original-cells original-cells--tape">
          <summary>{t("preview.original")}</summary>
          <p>{item.original.join(", ")}</p>
        </details>
      )}

      <div className="reasons">
        <strong>{t("preview.rejected")}</strong>
        {item.reasons.map((reason) => (
          <p key={reason}>{reason}</p>
        ))}
        {reasonCount > 1 && (
          <p className="row-resolver__batch-note">
            {t("preview.resolve.batchCount", { count: formattedCount })}
          </p>
        )}
      </div>

      {onLoadRowContext && (
        <section className="row-context" aria-label={t("preview.context.title")}>
          <h3 className="row-context__heading">{t("preview.context.title")}</h3>
          {loadingContext && <p className="hint">{t("preview.context.loading")}</p>}
          {contextError && (
            <p className="field__error" role="status">
              {t("preview.context.error", { reason: contextError })}
            </p>
          )}
          {context && (
            <div className="row-context__wrap">
              <table className="table table--context">
                <thead>
                  <tr>
                    <th scope="col">#</th>
                    {context.headers.map((header, colIdx) => (
                      <th
                        key={`${colIdx}-${header}`}
                        scope="col"
                        className={targetColumns.includes(colIdx) ? "row-context__th--error" : undefined}
                      >
                        {header}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {context.rows.map((entry) => (
                    <tr
                      key={entry.row_number}
                      className={[
                        entry.is_target ? "row-context__row--target" : "",
                        entry.row_class !== "data" ? "row-context__row--meta" : "",
                        entry.ignored ? "row-context__row--ignored" : "",
                      ]
                        .filter(Boolean)
                        .join(" ") || undefined}
                    >
                      <th scope="row" className="cell--row">
                        {entry.row_number}
                      </th>
                      {entry.cells.map((cell, colIdx) => {
                        const isFailingCell = entry.is_target && targetColumns.includes(colIdx);
                        const empty = cell.trim() === "";
                        return (
                          <td
                            key={colIdx}
                            className={isFailingCell ? "row-context__cell--error" : undefined}
                          >
                            {empty ? (
                              <span className="row-context__empty" aria-label={t("preview.context.emptyCell")}>
                                —
                              </span>
                            ) : (
                              cell
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {!readOnly && onResolveRows && (
        <div className="row-resolve">
          <div className="row-resolve__actions">
            {reasonCount > 1 && primaryReason ? (
              <>
                <Button
                  variant="primary"
                  disabled={resolving}
                  onClick={() => void resolve({ action: "ignore_by_reason", reason: primaryReason })}
                >
                  {t("preview.resolve.ignoreAll", { count: formattedCount })}
                </Button>
                <Button
                  variant="quiet"
                  disabled={resolving}
                  onClick={() => void resolve({ action: "ignore_row", row_number: item.row_number })}
                >
                  {t("preview.resolve.ignoreOnlyOne")}
                </Button>
              </>
            ) : (
              <Button
                variant="quiet"
                disabled={resolving}
                onClick={() => void resolve({ action: "ignore_row", row_number: item.row_number })}
              >
                {t("preview.resolve.ignoreOne")}
              </Button>
            )}
          </div>

          {context && targetColumns.length > 0 && (
            <form className="row-resolve__edit" onSubmit={handleEditSubmit}>
              {targetColumns.length > 1 && (
                <label className="field" htmlFor={colSelectId}>
                  <span className="field__label">{t("preview.resolve.columnLabel")}</span>
                  <select
                    id={colSelectId}
                    value={selectedColumn}
                    disabled={resolving}
                    onChange={(event) => handleColumnChange(Number(event.target.value))}
                  >
                    {targetColumns.map((colIdx) => (
                      <option key={colIdx} value={colIdx}>
                        {context.headers[colIdx] ?? `#${colIdx + 1}`}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <label className="field" htmlFor={editInputId}>
                <span className="field__label">
                  {t("preview.resolve.editLabel", { header: activeHeader })}
                </span>
                <input
                  id={editInputId}
                  type="text"
                  className="row-resolve__input"
                  value={draftValue}
                  placeholder={t("preview.resolve.editPlaceholder")}
                  disabled={resolving}
                  onChange={(event) => setDraftValue(event.target.value)}
                />
              </label>
              <div className="row-resolve__actions">
                <Button type="submit" disabled={resolving}>
                  {t("preview.resolve.applyOne")}
                </Button>
                {editReasonCount > 1 && editReason && (
                  <Button
                    disabled={resolving}
                    onClick={() =>
                      void resolve({
                        action: "edit_by_reason",
                        reason: editReason,
                        column_index: realColumnIndex,
                        value: draftValue,
                      })
                    }
                  >
                    {t("preview.resolve.applyAll", { count: formattedEditCount })}
                  </Button>
                )}
              </div>
            </form>
          )}

          {resolveError && (
            <p className="field__error" role="alert">
              {resolveError}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
