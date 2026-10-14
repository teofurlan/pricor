import type { PreviewPage } from "../../api/types";
import { useI18n } from "../../i18n";
import { Badge } from "../atoms/Badge";
import { Button } from "../atoms/Button";
import { StepTrace } from "../molecules/StepTrace";

interface Props {
  page: PreviewPage;
  busy: boolean;
  onPage(offset: number): void;
}

/** Every data row: the file's own cells on the left, the path to the final cost on the right. */
export function PreviewTable({ page, busy, onPage }: Props) {
  const { t } = useI18n();
  const first = page.items.length === 0 ? 0 : page.offset + 1;
  const last = page.offset + page.items.length;
  return (
    <div className="stack">
      <div className="table-wrap">
        <table className="table table--preview">
          <thead>
            <tr>
              <th>{t("preview.row")}</th>
              <th>{t("preview.original")}</th>
              <th>{t("preview.steps")}</th>
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
                    <StepTrace trace={item.trace} currency={item.record?.currency ?? null} />
                  )}
                </td>
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
