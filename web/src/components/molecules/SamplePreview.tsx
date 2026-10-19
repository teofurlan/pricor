import type { ColumnRole, ColumnState } from "../../api/types";
import { useI18n } from "../../i18n";

export interface SampleData {
  header: string[];
  rows: string[][];
}

interface Props {
  sample: SampleData | null;
  columns: ColumnState[];
  edits?: Record<number, ColumnRole>;
  showFinalCost?: boolean;
  finalCosts?: Array<string | null>;
}

export function SamplePreview({
  sample,
  columns,
  edits = {},
  showFinalCost = false,
  finalCosts,
}: Props) {
  const { t } = useI18n();

  if (!sample || sample.rows.length === 0) return null;

  const visibleColumns = sample.header
    .map((rawHeader, index) => {
      const col = columns.find((c) => c.index === index);
      const role = edits[index] ?? col?.role ?? null;
      return { index, rawHeader, role };
    })
    .filter((col) => col.role !== "ignore");

  const rows = sample.rows.slice(0, 5);

  return (
    <section className="sample-preview stack" aria-labelledby="sample-preview-title">
      <h2 id="sample-preview-title" className="subtitle">
        {t("sample.title")}
      </h2>
      <div className="table-wrap">
        <table className="table table--sample" data-testid="sample-preview-table">
          <thead>
            <tr>
              {visibleColumns.map((col) => {
                const isUndecided = col.role === null;
                const label = isUndecided
                  ? col.rawHeader || t("columns.noHeader", { n: col.index + 1 })
                  : t(`role.${col.role}`);
                return (
                  <th key={col.index} scope="col">
                    <span className={isUndecided ? "preview-th--muted" : "preview-th--role"}>
                      {label}
                    </span>
                  </th>
                );
              })}
              {showFinalCost && (
                <th scope="col" className="cell--cost">
                  {t("sample.finalCost")}
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {visibleColumns.map((col) => (
                  <td key={col.index}>{row[col.index] ?? ""}</td>
                ))}
                {showFinalCost && (
                  <td className="cell--cost">
                    {finalCosts && finalCosts[rowIndex] !== undefined && finalCosts[rowIndex] !== null
                      ? finalCosts[rowIndex]
                      : "—"}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
