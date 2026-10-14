import type { FxState, PreviewPage } from "../../api/types";
import { useI18n } from "../../i18n";
import { Badge } from "../atoms/Badge";
import { Button } from "../atoms/Button";
import { StepTrace } from "../molecules/StepTrace";

interface Props {
  page: PreviewPage;
  busy: boolean;
  onPage(offset: number): void;
  /** The run's conversion, when the plan has one: adds the converted column. */
  fx?: FxState | null;
}

/** Every data row: the file's own cells on the left, the path to the final cost on the right. */
export function PreviewTable({ page, busy, onPage, fx = null }: Props) {
  const { t } = useI18n();
  const first = page.items.length === 0 ? 0 : page.offset + 1;
  const last = page.offset + page.items.length;
  const showConverted = fx !== null;
  return (
    <div className="stack">
      <div className="table-wrap">
        <table className="table table--preview">
          <thead>
            <tr>
              <th>{t("preview.row")}</th>
              <th>{t("preview.original")}</th>
              <th>{t("preview.steps")}</th>
              {showConverted && <th>{t("preview.converted", { currency: fx.to })}</th>}
            </tr>
          </thead>
          <tbody>
            {page.items.map((item) => (
              <tr key={item.row_number} className={item.status === "rejected" ? "row--rejected" : undefined}>
                <th scope="row" className="cell--row">
                  {t("preview.rowNumber", { row: item.row_number })}
                </th>
                <td className="cell--original">{item.original.join(", ")}</td>
                <td>
                  {item.status === "rejected" ? (
                    <div className="reasons">
                      <Badge tone="bad">{t("preview.rejected")}</Badge>
                      {item.reasons.map((reason) => (
                        <p key={reason}>{reason}</p>
                      ))}
                    </div>
                  ) : (
                    <StepTrace
                      trace={item.trace}
                      currency={item.record?.currency ?? null}
                      convertedCurrency={fx?.to ?? null}
                    />
                  )}
                </td>
                {showConverted && (
                  <td className="cell--converted">
                    {item.record?.unit_cost_net_converted ? `${item.record.unit_cost_net_converted} ${fx.to}` : "—"}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="pager">
        <span>{t("preview.range", { first, last, total: page.total_items })}</span>
        <div className="actions">
          <Button disabled={busy || page.offset === 0} onClick={() => onPage(Math.max(0, page.offset - page.limit))}>
            {t("preview.previous")}
          </Button>
          <Button disabled={busy || last >= page.total_items} onClick={() => onPage(page.offset + page.limit)}>
            {t("preview.next")}
          </Button>
        </div>
      </div>
    </div>
  );
}
