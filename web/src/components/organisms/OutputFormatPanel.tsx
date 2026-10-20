import { useId, useRef, useState, type FormEvent } from "react";
import type { OutputColumnDefinition, OutputFormat, OutputFormatColumn } from "../../api/types";
import { isTextKey, useI18n, type TextKey } from "../../i18n";
import { Button } from "../atoms/Button";
import { TapeLoader } from "../atoms/TapeLoader";
import { usePendingAction } from "../atoms/usePendingAction";

interface Props {
  format: OutputFormat | null;
  loading: boolean;
  busy: boolean;
  error: string | null;
  /** The product file's fields a column can take its value from, in file order. */
  fields: string[];
  onUpload(file: File): void;
  /** Exactly these columns, in this order, become the confirmed format. */
  onSave(columns: OutputColumnDefinition[]): void;
  onRemove(): void;
}

interface Row {
  key: number;
  name: string;
  /** `field:<name>`, `empty` or `constant`. */
  kind: string;
  fixed: string;
  /** The template column this row came from; null for a column added by hand. */
  template: OutputFormatColumn | null;
}

function rowsFrom(format: OutputFormat | null, nextKey: () => number): Row[] {
  if (!format) return [];
  return format.columns.map((column) => {
    const source = column.source ?? column.proposal.source;
    const constant = source.startsWith("constant:");
    return {
      key: nextKey(),
      name: column.name,
      kind: constant ? "constant" : source,
      fixed: constant ? source.slice("constant:".length) : "",
      // A hand-made column has no template behind it, even after it is saved.
      template: column.proposal.proposed_by === "user" ? null : column,
    };
  });
}

function definition(row: Row): OutputColumnDefinition {
  return {
    name: row.name.trim(),
    source: row.kind === "constant" ? `constant:${row.fixed.trim()}` : row.kind,
    template_index: row.template ? row.template.index : null,
  };
}

/** What keeps a row from being saved; a repeated name is flagged on the later column only. */
function problem(row: Row, earlier: Row[]): TextKey | null {
  const name = row.name.trim().toLocaleLowerCase();
  if (name === "") return "format.error.name";
  if (earlier.some((other) => other.name.trim().toLocaleLowerCase() === name)) return "format.error.duplicate";
  if (row.kind === "constant" && row.fixed.trim() === "") return "format.error.fixed";
  return null;
}

/**
 * The columns of the products file. The user loads a template (Gemma or a rule proposes where
 * each column comes from), adds columns by hand, or both. The file has exactly these columns,
 * in this order, and only once the user saves them.
 */
export function OutputFormatPanel({ format, loading, busy, error, fields, onUpload, onSave, onRemove }: Props) {
  const { t } = useI18n();
  const pending = usePendingAction<"upload" | "save" | "remove">(busy);
  const fileId = useId();
  const titleId = useId();
  const keys = useRef(0);
  const nextKey = () => ++keys.current;
  const [file, setFile] = useState<File | null>(null);
  const [rows, setRows] = useState<Row[]>(() => rowsFrom(format, nextKey));
  // A new or saved format from the server replaces the rows being edited.
  const [shown, setShown] = useState(format);
  if (format !== shown) {
    setShown(format);
    setRows(rowsFrom(format, nextKey));
  }

  const available = format?.fields ?? fields;
  const fieldLabel = (name: string) => {
    const key = `field.${name}`;
    return isTextKey(key) ? t(key) : name;
  };
  const problems = rows.map((row, index) => problem(row, rows.slice(0, index)));
  const definitions = rows.map(definition);
  const saved = format?.state === "confirmed" ? rowsFrom(format, () => 0).map(definition) : null;
  const unchanged = saved !== null && JSON.stringify(saved) === JSON.stringify(definitions);
  const canSave = rows.length > 0 && problems.every((item) => item === null) && !unchanged && !busy;

  function upload(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    pending.mark("upload");
    onUpload(file);
  }

  function edit(key: number, change: Partial<Row>) {
    setRows((current) => current.map((row) => (row.key === key ? { ...row, ...change } : row)));
  }

  function move(index: number, offset: number) {
    setRows((current) => {
      const next = [...current];
      [next[index], next[index + offset]] = [next[index + offset], next[index]];
      return next;
    });
  }

  function add() {
    setRows((current) => [...current, { key: nextKey(), name: "", kind: `field:${available[0]}`, fixed: "", template: null }]);
  }

  function reset() {
    if (format) {
      pending.mark("remove");
      onRemove();
    } else {
      setRows([]);
    }
  }

  if (loading) return <TapeLoader text={t("common.loading")} />;

  const state = rows.length === 0 ? "standard" : unchanged ? "confirmed" : "proposed";

  return (
    <section className="output-format stack" aria-labelledby={titleId}>
      <header>
        <h2 className="subtitle" id={titleId}>{t("format.title")}</h2>
        <p className="lede">{t("format.lede")}</p>
      </header>

      <form className="output-format__upload" onSubmit={upload}>
        <label htmlFor={fileId} className="field__label">{t("format.file")}</label>
        <input id={fileId} type="file" accept=".csv,.xls,.xlsx,.xlsm" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
        <Button type="submit" disabled={!file || busy} loading={pending.isLoading("upload")}>{t("format.read")}</Button>
      </form>

      {error && <p className="memory-panel__error" role="alert">{error}</p>}

      {format && format.name !== "" && <p className="hint">{t("format.template", { name: format.name })}</p>}

      {rows.length > 0 && (
        <ol className="output-format__columns" aria-label={t("format.columns")}>
          {rows.map((row, index) => {
            const label = row.name.trim() || t("format.unnamed", { n: index + 1 });
            const issue = problems[index];
            const issueId = `${titleId}-issue-${row.key}`;
            return (
              <li key={row.key} className="output-format__column">
                <span className="output-format__position" aria-hidden="true">{index + 1}</span>
                <div className="output-format__fields">
                  <input
                    className="output-format__name"
                    aria-label={t("format.nameFor", { n: index + 1 })}
                    placeholder={t("format.namePlaceholder")}
                    value={row.name}
                    maxLength={100}
                    aria-invalid={issue === "format.error.name" || issue === "format.error.duplicate"}
                    aria-describedby={issue ? issueId : undefined}
                    onChange={(event) => edit(row.key, { name: event.target.value })}
                  />
                  <div className="output-format__source">
                    <select aria-label={t("format.sourceFor", { name: label })} value={row.kind} onChange={(event) => edit(row.key, { kind: event.target.value })}>
                      {available.map((field) => <option key={field} value={`field:${field}`}>{fieldLabel(field)}</option>)}
                      <option value="empty">{t("format.empty")}</option>
                      <option value="constant">{t("format.fixed")}</option>
                    </select>
                    {row.kind === "constant" && (
                      <input
                        aria-label={t("format.fixedFor", { name: label })}
                        value={row.fixed}
                        maxLength={200}
                        aria-invalid={issue === "format.error.fixed"}
                        onChange={(event) => edit(row.key, { fixed: event.target.value })}
                      />
                    )}
                  </div>
                  {row.template && (
                    <p className="output-format__meta">
                      {row.template.samples.length > 0 && <span className="cell__samples">{row.template.samples.join(", ")}</span>}
                      <span>
                        {row.template.proposal.proposed_by === "gemma"
                          ? `Gemma ${Math.round(row.template.proposal.confidence * 100)}%`
                          : t("format.rule")}
                      </span>
                    </p>
                  )}
                  {issue && <p id={issueId} className="output-format__issue">{t(issue)}</p>}
                </div>
                <div className="output-format__keys">
                  <button type="button" className="icon-key" aria-label={t("format.moveUp", { name: label })} disabled={busy || index === 0} onClick={() => move(index, -1)}>↑</button>
                  <button type="button" className="icon-key" aria-label={t("format.moveDown", { name: label })} disabled={busy || index === rows.length - 1} onClick={() => move(index, 1)}>↓</button>
                  <button type="button" className="icon-key" aria-label={t("format.removeColumn", { name: label })} disabled={busy} onClick={() => setRows((current) => current.filter((item) => item.key !== row.key))}>×</button>
                </div>
              </li>
            );
          })}
        </ol>
      )}

      <Button className="output-format__add" disabled={busy || rows.length >= 200} onClick={add}>
        <span aria-hidden="true">+ </span>{t("format.add")}
      </Button>

      <p className={`output-format__state output-format__state--${state}`}>
        {t(state === "standard" ? "format.standard" : state === "confirmed" ? "format.confirmed" : "format.proposed")}
      </p>
      {rows.length > 0 && <p className="hint">{t("format.exact")}</p>}

      {(rows.length > 0 || format) && (
        <div className="actions">
          <Button
            variant="primary"
            disabled={!canSave}
            loading={pending.isLoading("save")}
            onClick={() => { pending.mark("save"); onSave(definitions); }}
          >
            {t("format.confirm")}
          </Button>
          <Button disabled={busy} loading={pending.isLoading("remove")} onClick={reset}>
            {t("format.remove")}
          </Button>
        </div>
      )}
    </section>
  );
}
