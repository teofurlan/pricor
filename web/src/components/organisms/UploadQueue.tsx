import { useEffect, useRef, useState } from "react";
import { ApiError } from "../../api/client";
import { useI18n } from "../../i18n";
import { describeError } from "../../i18n/serverText";
import { Button } from "../atoms/Button";

export interface QueueDraft {
  file: File;
  supplierName: string;
  sheet: string;
}

/** The supplier a file name suggests: the text before the first `_`, `-` or `.`. */
export function supplierFromFileName(name: string): string {
  const stem = name.split(/[_.-]/, 1)[0].trim();
  return stem || name.replace(/\.[^.]*$/, "").trim();
}

interface Props {
  files: File[];
  busy: boolean;
  onInspectSheets?(file: File): Promise<string[]>;
  onStart(items: QueueDraft[]): void;
  onCancel(): void;
}

/** Several files picked at once: a compact list to check each supplier name (and sheet) before the queue starts. */
export function UploadQueue({ files, busy, onInspectSheets, onStart, onCancel }: Props) {
  const { t, language } = useI18n();
  const [items, setItems] = useState<QueueDraft[]>(() =>
    files.map((file) => ({ file, supplierName: supplierFromFileName(file.name), sheet: "" })),
  );
  const [sheets, setSheets] = useState<Record<number, string[]>>({});
  const [problems, setProblems] = useState<Record<number, string>>({});
  // The parent passes a fresh function on every render; only a new set of files may restart the reading.
  const inspect = useRef(onInspectSheets);
  inspect.current = onInspectSheets;

  useEffect(() => {
    let active = true;
    setItems(files.map((file) => ({ file, supplierName: supplierFromFileName(file.name), sheet: "" })));
    setSheets({});
    setProblems({});
    files.forEach((file, index) => {
      inspect.current?.(file)
        .then((names) => { if (active) setSheets((known) => ({ ...known, [index]: names })); })
        .catch((failure: unknown) => {
          if (!active) return;
          const reason = failure instanceof ApiError ? describeError(failure, language) : failure instanceof Error ? failure.message : String(failure);
          setProblems((known) => ({ ...known, [index]: reason }));
        });
    });
    return () => { active = false; };
    // The language only words an error; re-reading the files for it would reset what was typed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [files]);

  const patch = (index: number, change: Partial<QueueDraft>) =>
    setItems((known) => known.map((item, position) => (position === index ? { ...item, ...change } : item)));
  const ready = !busy && items.every((item) => item.supplierName.trim() !== "");

  return (
    <div className="upload">
      <div className="form">
        <h2 className="subtitle">{t("queue.title")}</h2>
        <p className="hint">{t("queue.lede")}</p>
        <ul className="queue-draft">
          {items.map((item, index) => (
            <li key={`${item.file.name}-${index}`} className="queue-draft__row">
              <span className="queue-draft__file">{item.file.name}</span>
              <input
                aria-label={t("queue.supplier", { file: item.file.name })}
                value={item.supplierName}
                autoComplete="off"
                onChange={(event) => patch(index, { supplierName: event.target.value })}
              />
              {(sheets[index]?.length ?? 0) > 1 && (
                <select
                  aria-label={t("queue.sheet", { file: item.file.name })}
                  value={item.sheet}
                  onChange={(event) => patch(index, { sheet: event.target.value })}
                >
                  <option value="">{t("upload.sheetDefault")}</option>
                  {sheets[index].map((name) => <option key={name} value={name}>{name}</option>)}
                </select>
              )}
              {problems[index] && <p className="field__error" role="status">{t("upload.sheetsFailed", { reason: problems[index] })}</p>}
            </li>
          ))}
        </ul>
        <div className="actions">
          <Button variant="primary" disabled={!ready} onClick={() => onStart(items.map((item) => ({ ...item, supplierName: item.supplierName.trim() })))}>
            {t("queue.start")}
          </Button>
          <Button variant="quiet" onClick={onCancel}>{t("queue.change")}</Button>
        </div>
      </div>
    </div>
  );
}
