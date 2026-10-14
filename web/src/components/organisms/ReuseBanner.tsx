import type { PlanChange } from "../../api/types";
import { isTextKey, useI18n } from "../../i18n";

interface Props {
  version: number;
  supplier: string;
  changes: PlanChange[];
}

/** Calm notice that a saved plan is being reused, with what differs in the new file. */
export function ReuseBanner({ version, supplier, changes }: Props) {
  const { t } = useI18n();

  const column = (index: number | null) => (index === null ? "" : index + 1);
  const row = (index: number | null) => (index === null ? t("change.noHeader") : index + 1);

  function describe(change: PlanChange): { text: string; attention: boolean } {
    const common = { header: change.header, from: column(change.old_index), to: column(change.new_index) };
    switch (change.kind) {
      case "moved":
        return { text: t("change.moved", common), attention: false };
      case "retyped":
        return {
          text: t("change.retyped", { ...common, oldType: change.old_type ?? "", newType: change.new_type ?? "" }),
          attention: false,
        };
      case "new":
        return { text: t("change.new", common), attention: false };
      case "missing": {
        if (!change.used_by_plan) return { text: t("change.missing", common), attention: false };
        const roleKey = `role.${change.role}`;
        const role = isTextKey(roleKey) ? t(roleKey) : (change.role ?? "");
        return { text: t("change.missing.used", { ...common, role }), attention: true };
      }
      case "sheet_changed":
        return { text: t("change.sheet", { from: change.old_value ?? "", to: change.new_value ?? "" }), attention: false };
      case "header_row_changed":
        return {
          text: t("change.headerRow", { from: row(change.old_index), to: row(change.new_index) }),
          attention: false,
        };
    }
  }

  return (
    <section className="reuse" aria-labelledby="reuse-title">
      <h2 id="reuse-title" className="reuse__title">
        {t("reuse.title", { version, supplier })}
      </h2>
      <p className="hint">{t("reuse.lede")}</p>
      {changes.length === 0 ? (
        <p>{t("reuse.unchanged")}</p>
      ) : (
        <ul className="reuse__changes">
          {changes.map((change, position) => {
            const { text, attention } = describe(change);
            return (
              <li key={`${change.kind}-${change.header}-${position}`} className={attention ? "change--attention" : undefined}>
                {text}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
