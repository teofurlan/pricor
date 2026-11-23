import { useId, useRef, useState } from "react";
import type { OutputColumnDefinition, OutputFormat, OutputFormatColumn, OutputKind } from "../../api/types";
import { isTextKey, useI18n, type TextKey } from "../../i18n";
import { confidenceLevel } from "../../lib/confidence";
import { OUTPUT_KINDS, defaultKind, suggestSource } from "../../lib/outputKind";
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
  /** How the cell is written. */
  type: OutputKind;
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
      type: column.kind ?? defaultKind(source),
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
    kind: row.type,
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
  const hintId = useId();
  const titleId = useId();
  const keys = useRef(0);
  const nextKey = () => ++keys.current;
  const [file, setFile] = useState<File | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  // The user vouched for a template that did not look like a products file.
  const [vouched, setVouched] = useState(false);
  const [rows, setRows] = useState<Row[]>(() => rowsFrom(format, nextKey));
  // A new or saved format from the server replaces the rows being edited.
  const [shown, setShown] = useState(format);
  if (format !== shown) {
    setShown(format);
    setVouched(false);
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

  /** A chosen or dropped file is read at once; there is no separate "read" step. */
  function chooseFile(chosen: File | null) {
    setFile(chosen);
    if (!chosen) return;
    pending.mark("upload");
    onUpload(chosen);
  }

  function edit(key: number, change: Partial<Row>) {
    setRows((current) => current.map((row) => (row.key === key ? { ...row, ...change } : row)));
  }

  /**
   * A field implies a type. A fixed value or an empty column keeps a type the user chose, but drops
   * one that was only implied by the field it replaces.
   */
  function chooseSource(row: Row, kind: string) {
    if (kind.startsWith("field:")) return edit(row.key, { kind, type: defaultKind(kind) });
    const implied = row.kind.startsWith("field:") && row.type === defaultKind(row.kind);
    edit(row.key, { kind, type: implied ? "text" : row.type });
  }

  /** A type suggests where its value comes from, unless the source already fits or was set by hand. */
  function chooseType(row: Row, type: OutputKind) {
    const suggestion = suggestSource(type, row.kind);
    edit(row.key, suggestion !== null && (suggestion === "empty" || available.includes(suggestion.slice("field:".length))) ? { type, kind: suggestion } : { type });
  }

  function wrongFile() {
    setFile(null);
    if (fileInput.current) fileInput.current.value = "";
    pending.mark("remove");
    onRemove();
  }

  function move(index: number, offset: number) {
    setRows((current) => {
      const next = [...current];
      [next[index], next[index + offset]] = [next[index + offset], next[index]];
      return next;
    });
  }

  function add() {
    const kind = `field:${available[0]}`;
    setRows((current) => [...current, { key: nextKey(), name: "", kind, type: defaultKind(kind), fixed: "", template: null }]);
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
  const blocked = format?.fit?.mismatch === true && !vouched;

  return (
    <section className="output-format stack" aria-labelledby={titleId}>
      <header>
        <h2 className="subtitle" id={titleId}>{t("format.title")}</h2>
        <p className="lede">{t("format.lede")}</p>
      </header>

      <div className="field field--file">
        <label className="field__label" htmlFor={fileId}>{t("format.file")}</label>
        <div
          className={`dropzone${dragOver ? " dropzone--active" : ""}`}
          onClick={() => { if (!busy) fileInput.current?.click(); }}
          onDragOver={(event) => { event.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragOver(false);
            const dropped = event.dataTransfer.files?.[0];
            if (dropped && !busy) chooseFile(dropped);
          }}
        >
          <input
            id={fileId}
            ref={fileInput}
            type="file"
            className="sr-only"
            accept=".csv,.xls,.xlsx,.xlsm,.pdf"
            aria-describedby={hintId}
            disabled={busy}
            onChange={(event) => chooseFile(event.target.files?.[0] ?? null)}
          />
          {pending.isLoading("upload") ? (
            <TapeLoader size="small" text={t("format.reading")} />
          ) : dragOver ? (
            <p className="dropzone__main dropzone__main--active">{t("upload.dropActive")}</p>
          ) : file ? (
            <div className="dropzone__selected" aria-live="polite">
              <div className="dropzone__fileinfo"><span className="dropzone__filename">{file.name}</span></div>
              <button type="button" className="button button--key button--choose" disabled={busy} onClick={(event) => { event.stopPropagation(); fileInput.current?.click(); }}>
                {t("upload.changeFile")}
              </button>
            </div>
          ) : (
            <div className="dropzone__prompt">
              <p className="dropzone__main">{t("format.drop")}</p>
              <div className="dropzone__sub">
                <span className="dropzone__or">{t("upload.or")}</span>
                <button type="button" className="button button--key button--choose" disabled={busy} onClick={(event) => { event.stopPropagation(); fileInput.current?.click(); }}>
                  {t("upload.choose")}
                </button>
              </div>
            </div>
          )}
        </div>
        <span id={hintId} className="field__hint">{t("format.fileHint")}</span>
      </div>

      {error && <p className="memory-panel__error" role="alert">{error}</p>}

      {format && format.name !== "" && <p className="hint">{t("format.template", { name: format.name })}</p>}

      {blocked && format?.fit && (
        <div className="output-format__mismatch" role="alert">
          <p>{format.fit.unmatched.length > 0
            ? t("format.mismatch", { matched: format.fit.matched, total: format.fit.total, list: format.fit.unmatched.join(", ") })
            : t("format.mismatchNoList", { matched: format.fit.matched, total: format.fit.total })}</p>
          <div className="actions">
            <Button variant="primary" disabled={busy} onClick={() => setVouched(true)}>{t("format.mismatch.yes")}</Button>
            <Button className="button--decline" disabled={busy} loading={pending.isLoading("remove")} onClick={wrongFile}>{t("format.mismatch.no")}</Button>
          </div>
        </div>
      )}

      {!blocked && rows.length > 0 && (
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
                    <div className="output-format__field">
                      <label className="output-format__field-label" htmlFor={`${titleId}-kind-${row.key}`}>{t("format.kindLabel")}</label>
                      <select
                        id={`${titleId}-kind-${row.key}`}
                        aria-label={t("format.kindFor", { name: label })}
                        value={row.type}
                        onChange={(event) => chooseType(row, event.target.value as OutputKind)}
                      >
                        {OUTPUT_KINDS.map((type) => <option key={type} value={type}>{t(`format.kind.${type}`)}</option>)}
                      </select>
                    </div>
                    <div className="output-format__field">
                      <label className="output-format__field-label" htmlFor={`${titleId}-source-${row.key}`}>{t("format.sourceLabel")}</label>
                      <select
                        id={`${titleId}-source-${row.key}`}
                        aria-label={t("format.sourceFor", { name: label })}
                        value={row.kind}
                        onChange={(event) => chooseSource(row, event.target.value)}
                      >
                        <optgroup label={t("format.group.core")}>
                          {available.filter((field) => ["supplier_code", "description", "unit_cost_net", "currency"].includes(field)).map((field) => (
                            <option key={field} value={`field:${field}`}>{fieldLabel(field)}</option>
                          ))}
                        </optgroup>
                        <optgroup label={t("format.group.extra")}>
                          {available.filter((field) => !["supplier_code", "description", "unit_cost_net", "currency"].includes(field)).map((field) => (
                            <option key={field} value={`field:${field}`}>{fieldLabel(field)}</option>
                          ))}
                        </optgroup>
                        <optgroup label={t("format.group.other")}>
                          <option value="empty">{t("format.empty")}</option>
                          <option value="constant">{t("format.fixed")}</option>
                        </optgroup>
                      </select>
                    </div>
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
                          ? t("format.confidence", { level: t(`confidence.${confidenceLevel(row.template.proposal.confidence)}`) })
                          : t("format.rule")}
                      </span>
                    </p>
                  )}
                  {issue && <p id={issueId} className="output-format__issue">{t(issue)}</p>}
                </div>
                <div className="output-format__keys">
                  <button type="button" className="icon-key" aria-label={t("format.moveUp", { name: label })} disabled={busy || index === 0} onClick={() => move(index, -1)}>↑</button>
                  <button type="button" className="icon-key" aria-label={t("format.moveDown", { name: label })} disabled={busy || index === rows.length - 1} onClick={() => move(index, 1)}>↓</button>
                  <button type="button" className="icon-key icon-key--danger" aria-label={t("format.removeColumn", { name: label })} disabled={busy} onClick={() => setRows((current) => current.filter((item) => item.key !== row.key))}>×</button>
                </div>
              </li>
            );
          })}
        </ol>
      )}

      {!blocked && (
        <Button className="output-format__add" disabled={busy || rows.length >= 200} onClick={add}>
          <span aria-hidden="true">+ </span>{t("format.add")}
        </Button>
      )}

      <p className={`output-format__state output-format__state--${state}`}>
        {t(state === "standard" ? "format.standard" : state === "confirmed" ? "format.confirmed" : "format.proposed")}
      </p>
      {!blocked && rows.length > 0 && <p className="hint">{t("format.exact")}</p>}

      {!blocked && (rows.length > 0 || format) && (
        <div className="actions">
          <Button
            variant="primary"
            disabled={!canSave}
            loading={pending.isLoading("save")}
            onClick={() => { pending.mark("save"); onSave(definitions); }}
          >
            {t("format.confirm")}
          </Button>
          <Button className="button--danger" disabled={busy} loading={pending.isLoading("remove")} onClick={reset}>
            {t("format.remove")}
          </Button>
        </div>
      )}
    </section>
  );
}
