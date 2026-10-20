import { useId, useState, type FormEvent } from "react";
import type { OutputFormat, OutputSource } from "../../api/types";
import { isTextKey, useI18n } from "../../i18n";
import { Button } from "../atoms/Button";
import { TapeLoader } from "../atoms/TapeLoader";
import { usePendingAction } from "../atoms/usePendingAction";

interface Props {
  format: OutputFormat | null;
  loading: boolean;
  busy: boolean;
  error: string | null;
  onUpload(file: File): void;
  /** Every column's source, in template order. */
  onConfirm(sources: OutputSource[]): void;
  onRemove(): void;
}

interface Choice {
  /** `field:<name>`, `empty` or `constant`. */
  kind: string;
  fixed: string;
}

function choiceFrom(source: OutputSource): Choice {
  return source.startsWith("constant:") ? { kind: "constant", fixed: source.slice("constant:".length) } : { kind: source, fixed: "" };
}

function sourceFrom(choice: Choice): OutputSource {
  return choice.kind === "constant" ? `constant:${choice.fixed.trim()}` : choice.kind;
}

function initialChoices(format: OutputFormat | null): Choice[] {
  return format ? format.columns.map((column) => choiceFrom(column.source ?? column.proposal.source)) : [];
}

/**
 * The layout of the products file, read from a template. Gemma (or a rule) proposes where each
 * template column comes from; the format is used only after the user confirms it.
 */
export function OutputFormatPanel({ format, loading, busy, error, onUpload, onConfirm, onRemove }: Props) {
  const { t } = useI18n();
  const pending = usePendingAction<"upload" | "confirm" | "remove">(busy);
  const fileId = useId();
  const tableId = useId();
  const [file, setFile] = useState<File | null>(null);
  const [choices, setChoices] = useState<Choice[]>(() => initialChoices(format));
  // A new or re-confirmed format from the server replaces the choices being edited.
  const [shown, setShown] = useState(format);
  if (format !== shown) {
    setShown(format);
    setChoices(initialChoices(format));
  }

  const fieldLabel = (name: string) => {
    const key = `field.${name}`;
    return isTextKey(key) ? t(key) : name;
  };
  const incomplete = choices.some((choice) => choice.kind === "constant" && choice.fixed.trim() === "");

  function upload(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    pending.mark("upload");
    onUpload(file);
  }

  function choose(index: number, change: Partial<Choice>) {
    setChoices((current) => current.map((choice, position) => (position === index ? { ...choice, ...change } : choice)));
  }

  if (loading) return <TapeLoader text={t("common.loading")} />;

  return (
    <section className="output-format stack" aria-labelledby={`${tableId}-title`}>
      <header>
        <h2 className="subtitle" id={`${tableId}-title`}>{t("format.title")}</h2>
        <p className="lede">{t("format.lede")}</p>
      </header>
      {!format && <p className="hint">{t("format.standard")}</p>}

      <form className="output-format__upload" onSubmit={upload}>
        <label htmlFor={fileId} className="field__label">{t("format.file")}</label>
        {format && <span className="hint">{t("format.replace")}</span>}
        <input id={fileId} type="file" accept=".csv,.xls,.xlsx" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
        <Button type="submit" disabled={!file || busy} loading={pending.isLoading("upload")}>{t("format.read")}</Button>
      </form>

      {error && <p className="memory-panel__error" role="alert">{error}</p>}

      {format && (
        <>
          <p className={`output-format__state output-format__state--${format.state}`}>
            {t(format.state === "confirmed" ? "format.confirmed" : "format.proposed")}
          </p>
          <div className="table-wrap">
            <table className="table table--format" aria-label={t("format.columns")}>
              <thead>
                <tr>
                  <th scope="col">{t("format.col.name")}</th>
                  <th scope="col">{t("format.col.proposal")}</th>
                  <th scope="col">{t("format.col.source")}</th>
                </tr>
              </thead>
              <tbody>
                {format.columns.map((column, index) => {
                  const choice = choices[index] ?? choiceFrom(column.proposal.source);
                  return (
                    <tr key={column.index}>
                      <th scope="row">
                        <span className="cell__name">{column.name}</span>
                        {column.samples.length > 0 && <span className="cell__samples">{column.samples.join(", ")}</span>}
                      </th>
                      <td className="cell--status">
                        {column.proposal.proposed_by === "gemma" ? `Gemma ${Math.round(column.proposal.confidence * 100)}%` : t("format.rule")}
                      </td>
                      <td>
                        <div className="output-format__source">
                          <select aria-label={t("format.sourceFor", { name: column.name })} value={choice.kind} onChange={(event) => choose(index, { kind: event.target.value })}>
                            {format.fields.map((field) => <option key={field} value={`field:${field}`}>{fieldLabel(field)}</option>)}
                            <option value="empty">{t("format.empty")}</option>
                            <option value="constant">{t("format.fixed")}</option>
                          </select>
                          {choice.kind === "constant" && (
                            <input aria-label={t("format.fixedFor", { name: column.name })} value={choice.fixed} maxLength={200} onChange={(event) => choose(index, { fixed: event.target.value })} />
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="actions">
            <Button variant="primary" disabled={busy || incomplete} loading={pending.isLoading("confirm")} onClick={() => { pending.mark("confirm"); onConfirm(choices.map(sourceFrom)); }}>
              {t("format.confirm")}
            </Button>
            <Button disabled={busy} loading={pending.isLoading("remove")} onClick={() => { pending.mark("remove"); onRemove(); }}>
              {t("format.remove")}
            </Button>
          </div>
        </>
      )}
    </section>
  );
}
