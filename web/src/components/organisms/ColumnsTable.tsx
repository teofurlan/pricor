import { useState } from "react";
import { COLUMN_ROLES, type ColumnRole, type ColumnState } from "../../api/types";
import { localizeServerText } from "../../i18n/serverText";
import { useI18n } from "../../i18n";
import { Button } from "../atoms/Button";
import { SamplePreview, type SampleData } from "../molecules/SamplePreview";
import { usePendingAction } from "../atoms/usePendingAction";

interface Props {
  columns: ColumnState[];
  issues: string[];
  busy: boolean;
  sample?: SampleData | null;
  /** Only the roles the user changed, keyed by column index. */
  onConfirm(edits: Record<number, ColumnRole>): void;
}

export interface ParsedProposal {
  stage: string;
  role: ColumnRole;
  score: number;
  modelName: string;
  isUncalibrated: boolean;
  rationale?: string;
}

function getModelName(stage: string): string {
  const s = stage.toLowerCase();
  if (s.includes("laya")) return "Laya";
  if (s.includes("gemma")) return "Gemma";
  if (s.includes("heuristics")) return "keyword rules";
  return stage.charAt(0).toUpperCase() + stage.slice(1);
}

export function parseProposals(column: ColumnState): ParsedProposal[] {
  if (column.proposals && column.proposals.length > 0) {
    return column.proposals.map((p) => {
      const isUncalibrated = p.stage.toLowerCase().includes("gemma");
      return {
        stage: p.stage,
        role: p.role,
        score: p.score,
        modelName: getModelName(p.stage),
        isUncalibrated,
        rationale: p.rationale,
      };
    });
  }
  if (column.rationale) {
    const parts = column.rationale.split("|").map((s) => s.trim());
    const matched = parts
      .map((part): ParsedProposal | null => {
        const match = part.match(/^([a-z_]+):\s*([a-z_]+)\s*\((~?0?\.\d+)\)/i);
        if (!match) return null;
        const stage = match[1];
        const role = match[2].toLowerCase() as ColumnRole;
        const rawScore = match[3];
        const isUncalibrated = stage.toLowerCase().includes("gemma") || rawScore.startsWith("~");
        const numScore = parseFloat(rawScore.replace(/^~/, ""));
        return {
          stage,
          role,
          score: isNaN(numScore) ? 0.5 : numScore,
          modelName: getModelName(stage),
          isUncalibrated,
          rationale: part,
        };
      })
      .filter((m): m is ParsedProposal => m !== null);
    if (matched.length > 0) return matched;
  }
  if (column.score > 0 && column.role) {
    const isUncalibrated = (column.decided_by ?? "").toLowerCase().includes("gemma");
    return [
      {
        stage: column.decided_by ?? "heuristics",
        role: column.role,
        score: column.score,
        modelName: getModelName(column.decided_by ?? "heuristics"),
        isUncalibrated,
        rationale: column.rationale,
      },
    ];
  }
  return [];
}

export function getBestProposal(column: ColumnState): ParsedProposal | null {
  const proposals = parseProposals(column);
  if (proposals.length === 0) return null;
  return proposals.reduce((best, p) => (p.score > best.score ? p : best), proposals[0]);
}

function ConfidenceMeter({
  best,
  allProposals,
}: {
  best: ParsedProposal;
  allProposals: ParsedProposal[];
}) {
  const { t } = useI18n();
  const percentage = Math.round(best.score * 100);
  const uncalText = best.isUncalibrated ? " (uncalibrated)" : "";
  const ariaLabel = `Model confidence ${percentage} %${uncalText}, proposed by ${best.modelName}`;

  let tooltip = ariaLabel;
  if (allProposals.length > 1) {
    const others = allProposals
      .filter((p) => p !== best)
      .map(
        (p) =>
          `${p.modelName}: ${t(`role.${p.role}`)} (${Math.round(p.score * 100)}%${p.isUncalibrated ? " uncalibrated" : ""})`,
      )
      .join(", ");
    tooltip += ` · Other proposals: ${others}`;
  }

  // 5 segments: filled = round(score * 5), with at least 1 filled segment when score > 0
  const filledCount = best.score > 0 ? Math.max(1, Math.min(5, Math.round(best.score * 5))) : 0;

  const levelClass =
    filledCount >= 4
      ? "meter--sage"
      : filledCount === 3
        ? "meter--ochre"
        : filledCount >= 1
          ? "meter--brick"
          : "meter--none";

  return (
    <div
      className={`meter ${levelClass} meter--level-${filledCount}`}
      role="meter"
      aria-valuenow={percentage}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={ariaLabel}
      title={tooltip}
    >
      {[...Array(5)].map((_, i) => (
        <span
          key={i}
          className={`meter__seg ${i < filledCount ? "meter__seg--filled" : "meter__seg--empty"}`}
          aria-hidden="true"
        />
      ))}
    </div>
  );
}

/**
 * A key that reads "Change ▾" with a transparent native select laid over it.
 * Picking commits at once, so it never replaces the row's other keys and has no
 * mode to escape from. The overlay keeps the key as wide as its label, since a
 * bare select sizes itself to its longest option.
 */
function RolePicker({
  label,
  current,
  onPick,
}: {
  label: string;
  current: ColumnRole | null;
  onPick(role: ColumnRole): void;
}) {
  const { t } = useI18n();
  return (
    <span className="button button--key button--action role-picker">
      <span aria-hidden="true">{t("columns.change")}</span>
      <select
        className="role-picker__select"
        aria-label={label}
        value=""
        onChange={(event) => {
          const value = event.target.value as ColumnRole | "";
          if (value) onPick(value);
        }}
      >
        <option value="" disabled hidden>
          {t("columns.change")}
        </option>
        {COLUMN_ROLES.map((option) => (
          <option key={option} value={option}>
            {option === current ? `✓ ${t(`role.${option}`)}` : t(`role.${option}`)}
          </option>
        ))}
      </select>
    </span>
  );
}

export function ColumnsTable({ columns, issues, busy, sample, onConfirm }: Props) {
  const { t, language } = useI18n();
  const pending = usePendingAction<"confirm">(busy);
  const [edits, setEdits] = useState<Record<number, ColumnRole>>({});

  const unresolved = columns.filter((item) => item.role === null && edits[item.index] === undefined);

  const pendingSuggestionsCount = columns.filter(
    (item) => item.role === null && edits[item.index] === undefined && getBestProposal(item) !== null,
  ).length;

  function handleAcceptAll() {
    setEdits((current) => {
      const next = { ...current };
      for (const item of columns) {
        if (item.role === null && next[item.index] === undefined) {
          const best = getBestProposal(item);
          if (best) {
            next[item.index] = best.role;
          }
        }
      }
      return next;
    });
  }

  return (
    <div className="stack">
      {issues.length > 0 && (
        <ul className="issues">
          {issues.map((issue) => (
            <li key={issue}>{localizeServerText(issue, language)}</li>
          ))}
        </ul>
      )}

      {pendingSuggestionsCount > 0 && (
        <div className="table-actions-top">
          <Button
            variant="quiet"
            className="button--key button--action"
            disabled={busy}
            onClick={handleAcceptAll}
          >
            {t("columns.acceptAll")}
          </Button>
        </div>
      )}

      <div className="table-wrap">
        <table className="table table--columns">
          {/* Fixed widths: a key appearing or disappearing must not resize the other columns. */}
          <colgroup>
            <col className="col--column" />
            <col className="col--role" />
            <col className="col--actions" />
            <col className="col--status" />
            <col className="col--suggestion" />
          </colgroup>
          <thead>
            <tr>
              <th>{t("columns.header")}</th>
              {/* The role spans its value and its keys, so the keys line up in one column. */}
              <th colSpan={2}>{t("columns.role")}</th>
              <th>{t("columns.status")}</th>
              <th>{t("columns.suggestion")}</th>
            </tr>
          </thead>
          <tbody>
            {columns.map((item) => {
              const edited = edits[item.index];
              const role = edited ?? item.role;
              const needsUser = role === null;
              const bestProposal = getBestProposal(item);
              const allProposals = parseProposals(item);

              // Status determination
              let statusText = t("status.needs_confirmation");
              let statusClass = "status--pending";
              if (edited !== undefined) {
                statusText = t("status.user");
                statusClass = "status--user";
              } else if (item.decided_by === "user") {
                statusText = t("status.user");
                statusClass = "status--user";
              } else if (item.decided_by === "saved_plan") {
                statusText = t("status.saved_plan");
                statusClass = "status--saved";
              } else if (item.role !== null && item.decided_by !== null) {
                statusText = t("status.model_confident");
                statusClass = "status--model";
              }

              return (
                <tr key={item.index} className={needsUser ? "row--attention" : undefined}>
                  <th scope="row">
                    <span className="cell__name">{item.header || t("columns.noHeader", { n: item.index + 1 })}</span>
                    <span className="cell__samples">{item.samples.join(", ")}</span>
                  </th>
                  <td className="cell--role">
                    {role !== null ? <span className="role-decision__value">{t(`role.${role}`)}</span> : <span className="role-decision__empty" aria-hidden="true">—</span>}
                  </td>
                  <td className="cell--actions">
                    <div className="role-actions">
                      {edited !== undefined && (
                        <button
                          type="button"
                          className="button button--key button--action"
                          onClick={() =>
                            setEdits((current) => {
                              const next = { ...current };
                              delete next[item.index];
                              return next;
                            })
                          }
                        >
                          {t("columns.backToSuggestion")}
                        </button>
                      )}
                      {needsUser && bestProposal && (
                        <button
                          type="button"
                          className="button button--key button--action"
                          onClick={() => setEdits((cur) => ({ ...cur, [item.index]: bestProposal.role }))}
                        >
                          {t("columns.accept")}
                        </button>
                      )}
                      {needsUser && bestProposal?.role !== "ignore" && (
                        <button
                          type="button"
                          className="button button--key button--action"
                          onClick={() => setEdits((cur) => ({ ...cur, [item.index]: "ignore" }))}
                        >
                          {t("columns.ignore")}
                        </button>
                      )}
                      <RolePicker
                        label={t("columns.roleFor", { header: item.header || item.index + 1 })}
                        current={role}
                        onPick={(value) => setEdits((cur) => ({ ...cur, [item.index]: value }))}
                      />
                    </div>
                  </td>
                  <td className="cell--status">
                    <span className={`status-badge ${statusClass}`}>{statusText}</span>
                  </td>
                  <td className="cell--suggestion">
                    {bestProposal ? (
                      <div className="suggestion-box">
                        <ConfidenceMeter best={bestProposal} allProposals={allProposals} />
                        <span className="suggestion__label">{t(`role.${bestProposal.role}`)}</span>
                      </div>
                    ) : (
                      <span className="cell__empty">—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="actions">
        <Button variant="primary" disabled={busy || unresolved.length > 0} loading={pending.isLoading("confirm")} onClick={() => { pending.mark("confirm"); onConfirm(edits); }}>
          {t("columns.confirm")}
        </Button>
        {unresolved.length > 0 && (
          <span className="hint">
            {t(unresolved.length === 1 ? "columns.remaining.one" : "columns.remaining.other", { count: unresolved.length })}
          </span>
        )}
      </div>

      {sample && sample.rows.length > 0 && (
        <SamplePreview sample={sample} columns={columns} edits={edits} />
      )}
    </div>
  );
}
