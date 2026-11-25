import { confidenceLevel } from "../../lib/confidence";
import { useEffect, useState } from "react";
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
  if (s.includes("heuristics")) return "automatic detection";
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
  const ariaLabel = t("columns.confidenceLabel", { level: t(`confidence.${confidenceLevel(best.score)}`), confidence: `${percentage} %` });

  let tooltip = ariaLabel;
  if (allProposals.length > 1) {
    const others = allProposals
      .filter((p) => p !== best)
      .map(
        (p) =>
          `${t(`role.${p.role}`)} (${t(`confidence.${confidenceLevel(p.score)}`)})`,
      )
      .join(", ");
    tooltip += ` · ${t("columns.otherProposals", { list: others })}`;
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
const REQUIRED_ROLES: readonly ColumnRole[] = ["code", "description", "cost_price"];
const OPTIONAL_ROLES: readonly ColumnRole[] = COLUMN_ROLES.filter(
  (role) => !REQUIRED_ROLES.includes(role) && role !== "retail_price",
);

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
        <optgroup label={t("columns.group.required")}>
          {REQUIRED_ROLES.map((option) => (
            <option key={option} value={option}>
              {option === current ? `✓ ${t(`role.${option}`)}` : t(`role.${option}`)}
            </option>
          ))}
        </optgroup>
        <optgroup label={t("columns.group.optional")}>
          {OPTIONAL_ROLES.map((option) => (
            <option key={option} value={option}>
              {option === current ? `✓ ${t(`role.${option}`)}` : t(`role.${option}`)}
            </option>
          ))}
        </optgroup>
      </select>
    </span>
  );
}

/** Roles the plan needs exactly one column for; two columns with the same one cannot be confirmed. */
const UNIQUE_ROLES: readonly ColumnRole[] = ["code", "description", "cost_price"];
/** A column empty in at least this share of the data rows gets a completeness note. */
const EMPTY_NOTE_SHARE = 0.05;

export function ColumnsTable({ columns, issues, busy, sample, onConfirm }: Props) {
  const { t, language } = useI18n();
  const pending = usePendingAction<"confirm">(busy);
  const [edits, setEdits] = useState<Record<number, ColumnRole>>({});

  const unresolved = columns.filter((item) => item.role === null && edits[item.index] === undefined);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key === "Enter" && !busy && unresolved.length === 0) {
        const tag = (event.target as HTMLElement | null)?.tagName;
        if (tag === "TEXTAREA") return;
        event.preventDefault();
        pending.mark("confirm");
        onConfirm(edits);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [busy, unresolved.length, edits, onConfirm, pending]);

  const pendingSuggestionsCount = columns.filter(
    (item) => item.role === null && edits[item.index] === undefined && getBestProposal(item) !== null,
  ).length;

  const roleCounts = new Map<ColumnRole, number>();
  for (const item of columns) {
    const role = edits[item.index] ?? item.role;
    if (role !== null) roleCounts.set(role, (roleCounts.get(role) ?? 0) + 1);
  }

  function handleAcceptAll() {
    setEdits((current) => {
      const next = { ...current };
      const taken = new Set<ColumnRole>();
      for (const item of columns) {
        const role = next[item.index] ?? item.role;
        if (role !== null) taken.add(role);
      }
      // The best-scored suggestion goes first, so when two collide on a unique role it is the one
      // accepted; the other stays for the user instead of creating a duplicate.
      const pending = columns
        .filter((item) => item.role === null && next[item.index] === undefined)
        .map((item) => ({ item, best: getBestProposal(item) }))
        .sort((a, b) => (b.best?.score ?? 0) - (a.best?.score ?? 0));
      for (const { item, best } of pending) {
        if (!best) continue;
        if (UNIQUE_ROLES.includes(best.role) && taken.has(best.role)) continue;
        next[item.index] = best.role;
        taken.add(best.role);
      }
      return next;
    });
  }

  // "always" keeps the Spanish thousands dot on four-digit numbers (2.043); older lib typings omit it.
  const numbers = new Intl.NumberFormat(language, { useGrouping: "always" } as unknown as Intl.NumberFormatOptions);

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
            className="button--key button--action button--accept-all"
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
            <col className="col--suggestion" />
            <col className="col--role" />
            <col className="col--actions" />
            <col className="col--status" />
          </colgroup>
          <thead>
            <tr>
              <th scope="col">{t("columns.header")}</th>
              <th scope="col">{t("columns.suggestion")}</th>
              {/* The role spans its value and its keys right next to the suggestion. */}
              <th scope="col" colSpan={2}>{t("columns.role")}</th>
              <th scope="col">{t("columns.status")}</th>
            </tr>
          </thead>
          <tbody>
            {columns.map((item) => {
              const edited = edits[item.index];
              const role = edited ?? item.role;
              const needsUser = role === null;
              const bestProposal = getBestProposal(item);
              const allProposals = parseProposals(item);
              const duplicated = role !== null && UNIQUE_ROLES.includes(role) && (roleCounts.get(role) ?? 0) > 1;
              const emptyRows = item.empty_rows ?? 0;
              const dataRows = item.data_rows ?? 0;
              const mostlyFilled = dataRows === 0 || emptyRows < EMPTY_NOTE_SHARE * dataRows;

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
                    {item.quantity_discount && <span className="cell__samples">{t("columns.quantityDiscount")}</span>}
                    {!mostlyFilled && (
                      <span className="cell__samples">
                        {t("columns.emptyRows", { empty: numbers.format(emptyRows), total: numbers.format(dataRows) })}
                      </span>
                    )}
                    {duplicated && <span className="cell__samples" role="alert">{t("columns.duplicateRole", { role: t(`role.${role}`) })}</span>}
                  </th>
                  <td className="cell--suggestion" data-label={t("columns.suggestion")}>
                    {bestProposal ? (
                      <div className="suggestion-box">
                        <ConfidenceMeter best={bestProposal} allProposals={allProposals} />
                        <span className="suggestion__label">{t(`role.${bestProposal.role}`)}</span>
                      </div>
                    ) : (
                      <span className="cell__empty">—</span>
                    )}
                  </td>
                  <td className="cell--role" data-label={t("columns.role")}>
                    {role !== null ? <span className="role-decision__value">{t(`role.${role}`)}</span> : <span className="role-decision__empty" aria-hidden="true">—</span>}
                  </td>
                  <td className="cell--actions">
                    <div className="role-actions">
                      {edited !== undefined && (
                        <button
                          type="button"
                          className="button button--key button--action button--undo"
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
                          className="button button--key button--action button--accept"
                          onClick={() => setEdits((cur) => ({ ...cur, [item.index]: bestProposal.role }))}
                        >
                          {t("columns.accept")}
                        </button>
                      )}
                      {needsUser && bestProposal?.role !== "ignore" && (
                        <button
                          type="button"
                          className="button button--key button--action button--ignore"
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
                  <td className="cell--status" data-label={t("columns.status")}>
                    <span className={`status-badge ${statusClass}`}>{statusText}</span>
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
