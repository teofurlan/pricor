import { useState, type FormEvent } from "react";
import type { Memory } from "../../api/types";
import { useI18n } from "../../i18n";
import { Badge } from "../atoms/Badge";
import { Button } from "../atoms/Button";

interface Props {
  memories: Memory[];
  loading: boolean;
  busy: boolean;
  error?: string | null;
  onAdd(text: string, supplierName?: string): void;
  onEdit(id: string, text: string): void;
  onDelete(id: string): void;
}

export function MemoryPanel({ memories, loading, busy, error = null, onAdd, onEdit, onDelete }: Props) {
  const { t, language } = useI18n();
  const [text, setText] = useState("");
  const [supplier, setSupplier] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [editText, setEditText] = useState("");

  function submit(event: FormEvent) {
    event.preventDefault();
    const note = text.trim();
    if (!note) return;
    onAdd(note, supplier.trim() || undefined);
    setText("");
    setSupplier("");
  }

  const date = new Intl.DateTimeFormat(language === "es" ? "es-AR" : "en-US", { dateStyle: "medium" });

  return (
    <section className="memory-panel" aria-labelledby="memory-panel-title">
      <header className="memory-panel__header">
        <div>
          <h2 id="memory-panel-title" className="subtitle">{t("memory.title")}</h2>
          <p className="lede">{t("memory.lede")}</p>
        </div>
      </header>

      <form className="memory-note" onSubmit={submit}>
        <label htmlFor="memory-note-text">{t("memory.note.label")}</label>
        <textarea id="memory-note-text" value={text} onChange={(event) => setText(event.target.value)} rows={3} />
        <label htmlFor="memory-note-supplier">{t("memory.supplier.label")}</label>
        <input id="memory-note-supplier" value={supplier} onChange={(event) => setSupplier(event.target.value)} />
        <Button variant="primary" type="submit" disabled={busy || text.trim() === ""}>{t("memory.add")}</Button>
      </form>

      {error && <p className="memory-panel__error" role="alert">{error}</p>}
      {loading ? (
        <p className="lede" aria-live="polite">{t("common.loading")}</p>
      ) : memories.length === 0 ? (
        <p className="memory-panel__empty">{t("memory.empty")}</p>
      ) : (
        <div className="memory-list">
          {memories.map((memory) => (
            <article key={memory.id} className="memory-card" aria-label={memory.text}>
              <div className="memory-card__meta">
                <Badge tone={memory.source === "user_note" ? "user" : "gemma"}>
                  {t(memory.source === "user_note" ? "memory.source.note" : "memory.source.suggestion")}
                </Badge>
                {memory.supplier_name && <span>{memory.supplier_name}</span>}
                <time dateTime={memory.updated_at}>{date.format(new Date(memory.updated_at))}</time>
              </div>
              {editing === memory.id ? (
                <div className="memory-card__editor">
                  <label htmlFor={`memory-${memory.id}`}>{t("memory.text.label")}</label>
                  <textarea id={`memory-${memory.id}`} rows={3} value={editText} onChange={(event) => setEditText(event.target.value)} />
                  <div className="actions">
                    <Button variant="primary" disabled={busy || editText.trim() === ""} onClick={() => { onEdit(memory.id, editText.trim()); setEditing(null); }}>{t("memory.save")}</Button>
                    <Button disabled={busy} onClick={() => setEditing(null)}>{t("memory.cancel")}</Button>
                  </div>
                </div>
              ) : (
                <>
                  <p className="memory-card__text">{memory.text}</p>
                  <div className="actions">
                    <Button variant="link" disabled={busy} onClick={() => { setEditing(memory.id); setEditText(memory.text); }}>{t("memory.edit")}</Button>
                    <Button variant="link" disabled={busy} onClick={() => window.confirm(t("memory.delete.confirm")) && onDelete(memory.id)}>{t("memory.delete")}</Button>
                  </div>
                </>
              )}
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
