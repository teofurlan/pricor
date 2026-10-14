import { useState } from "react";
import { COLUMN_ROLES, type ColumnRole, type ColumnState } from "../../api/types";
import { useI18n } from "../../i18n";
import { Button } from "../atoms/Button";
import { ProvenanceBadge } from "../molecules/ProvenanceBadge";

interface Props {
  columns: ColumnState[];
  issues: string[];
  busy: boolean;
  /** Only the roles the user changed, keyed by column index. */
  onConfirm(edits: Record<number, ColumnRole>): void;
}

export function ColumnsTable({ columns, issues, busy, onConfirm }: Props) {
  const { t } = useI18n();
  const [edits, setEdits] = useState<Record<number, ColumnRole>>({});

  const unresolved = columns.filter((item) => item.role === null && edits[item.index] === undefined);

  return (
    <div className="stack">
      {issues.length > 0 && (
        <ul className="issues">
          {issues.map((issue) => (
            <li key={issue}>{issue}</li>
          ))}
        </ul>
      )}
      <div className="table-wrap">
        <table className="table table--columns">
          <thead>
            <tr>
              <th>{t("columns.header")}</th>
              <th>{t("columns.role")}</th>
              <th>{t("columns.decidedBy")}</th>
              <th>{t("columns.rationale")}</th>
            </tr>
          </thead>
          <tbody>
            {columns.map((item) => {
              const edited = edits[item.index];
              const role = edited ?? item.role;
              const needsUser = role === null;
              return (
                <tr key={item.index} className={needsUser ? "row--attention" : undefined}>
                  <th scope="row">
                    <span className="cell__name">{item.header || t("columns.noHeader", { n: item.index + 1 })}</span>
                    <span className="cell__samples">{item.samples.join(", ")}</span>
                  </th>
                  <td>
                    <select
                      aria-label={t("columns.roleFor", { header: item.header || item.index + 1 })}
                      value={role ?? ""}
                      onChange={(event) => {
                        const value = event.target.value as ColumnRole | "";
                        setEdits((current) => {
                          const next = { ...current };
                          if (value === "" || value === item.role) delete next[item.index];
                          else next[item.index] = value;
                          return next;
                        });
                      }}
                    >
                      {role === null && <option value="">{t("columns.choose")}</option>}
                      {COLUMN_ROLES.map((option) => (
                        <option key={option} value={option}>
                          {t(`role.${option}`)}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="cell--decided">
                    <ProvenanceBadge decidedBy={edited !== undefined ? "user" : item.decided_by} />
                    {edited === undefined && item.decided_by !== null && (
                      <span className="cell__score" title={t("columns.score")}>
                        {Number(item.score.toFixed(2))}
                      </span>
                    )}
                  </td>
                  <td className="cell--rationale" title={edited !== undefined ? undefined : item.rationale}>
                    <span className="cell__clamp">{edited !== undefined ? "" : item.rationale}</span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="actions">
        <Button variant="primary" disabled={busy || unresolved.length > 0} onClick={() => onConfirm(edits)}>
          {t("columns.confirm")}
        </Button>
        {unresolved.length > 0 && <span className="hint">{t("columns.remaining", { count: unresolved.length })}</span>}
      </div>
    </div>
  );
}
