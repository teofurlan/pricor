import { useEffect, useId, useRef, useState, type DragEvent, type FormEvent } from "react";
import type { CreateImportInput, Language, SampleListing } from "../../api/types";
import { ApiError } from "../../api/client";
import { useI18n } from "../../i18n";
import { describeError } from "../../i18n/serverText";
import { Button } from "../atoms/Button";
import { FileMark } from "../atoms/FileMark";
import { TapeLoader } from "../atoms/TapeLoader";
import { SamplePicker } from "../molecules/SamplePicker";

/** One file of a queue, as the user left it before starting. */
export interface QueueDraft {
  file: File;
  supplierName: string;
  sheet: string;
  language?: Language;
  forceFirstImport?: boolean;
}

/** The supplier a file name suggests: the text before the first `_`, `-` or `.`. */
export function supplierFromFileName(name: string): string {
  const stem = name.split(/[_.-]/, 1)[0].trim();
  return stem || name.replace(/\.[^.]*$/, "").trim();
}

interface Chosen extends QueueDraft {
  id: number;
  /** Sheet names once read; null while unknown. */
  sheets: string[] | null;
  reading: boolean;
  problem: string | null;
}

interface Props {
  busy: boolean;
  onSubmit(input: CreateImportInput): void;
  onInspectSheets?(file: File): Promise<string[]>;
  /** Several files at once: when given, files are added side by side and two or more start a queue. */
  onSubmitMany?(items: QueueDraft[]): void;
  /** Sample lists to try; the picker shows only when both are given and the list is not empty. */
  onListSamples?(): Promise<SampleListing[]>;
  onLoadSample?(sample: SampleListing): Promise<File>;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function splitName(name: string): { stem: string; extension: string } {
  const dot = name.lastIndexOf(".");
  return dot > 0 ? { stem: name.slice(0, dot), extension: name.slice(dot) } : { stem: name, extension: "" };
}

const sameFile = (a: File, b: File) => a.name === b.name && a.size === b.size && a.lastModified === b.lastModified;

export function UploadForm({ busy, onSubmit, onSubmitMany, onInspectSheets, onListSamples, onLoadSample }: Props) {
  const { t, language: interfaceLanguage } = useI18n();
  const many = onSubmitMany !== undefined;
  const [chosen, setChosen] = useState<Chosen[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [manualLanguage, setManualLanguage] = useState<Language | null>(null);
  const language = manualLanguage ?? interfaceLanguage;
  const [fresh, setFresh] = useState(false);
  const nextId = useRef(0);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const addKeyRef = useRef<HTMLButtonElement>(null);
  const added = useRef(false);
  const fileId = useId();
  const hintId = useId();
  const freshId = useId();
  const freshHintId = useId();

  const ready = !busy && chosen.length > 0 && chosen.every((item) => item.supplierName.trim() !== "" && !item.reading);
  const single = chosen.length === 1 ? chosen[0] : null;

  useEffect(() => {
    if (!added.current) return;
    added.current = false;
    addKeyRef.current?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
  }, [chosen.length]);

  const patch = (id: number, change: Partial<Chosen>) =>
    setChosen((known) => known.map((item) => (item.id === id ? { ...item, ...change } : item)));

  function inspect(item: Chosen) {
    if (!onInspectSheets) return;
    onInspectSheets(item.file)
      // A file removed or replaced meanwhile is no longer in the list, so its answer changes nothing.
      .then((names) => patch(item.id, { sheets: names, reading: false }))
      .catch((failure: unknown) => {
        const reason = failure instanceof ApiError ? describeError(failure, interfaceLanguage) : failure instanceof Error ? failure.message : String(failure);
        patch(item.id, { sheets: [], reading: false, problem: t("upload.sheetsFailed", { reason }) });
      });
  }

  function add(files: File[], supplierName?: string) {
    if (files.length === 0) return;
    const incoming = (many ? files : files.slice(0, 1)).map<Chosen>((file) => ({
      id: nextId.current++,
      file,
      supplierName: supplierName ?? supplierFromFileName(file.name),
      sheet: "",
      sheets: null,
      reading: onInspectSheets !== undefined,
      problem: null,
    }));
    const kept = many ? chosen : [];
    const newOnes = incoming.filter((item) => !kept.some((known) => sameFile(known.file, item.file)));
    if (newOnes.length === 0) return;
    setNotice(null);
    added.current = true;
    setChosen([...kept, ...newOnes]);
    newOnes.forEach(inspect);
  }

  const remove = (id: number) => setChosen((known) => known.filter((item) => item.id !== id));

  async function chooseSample(sample: SampleListing) {
    try {
      add([await onLoadSample!(sample)], sample.supplier_name);
    } catch (failure: unknown) {
      const reason = failure instanceof ApiError ? describeError(failure, interfaceLanguage) : failure instanceof Error ? failure.message : String(failure);
      setNotice(t("upload.sampleFailed", { reason }));
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!ready) return;
    if (single) {
      onSubmit({ file: single.file, supplierName: single.supplierName.trim(), sheet: single.sheet, language, ...(fresh && { forceFirstImport: true }) });
    } else {
      onSubmitMany?.(chosen.map(({ file, supplierName, sheet }) => ({ file, supplierName: supplierName.trim(), sheet, language, forceFirstImport: fresh })));
    }
  }

  const pick = () => fileInputRef.current?.click();
  const dropTarget = {
    onDragOver: (event: DragEvent) => { event.preventDefault(); setDragOver(true); },
    onDragLeave: () => setDragOver(false),
    onDrop: (event: DragEvent) => { event.preventDefault(); setDragOver(false); add(Array.from(event.dataTransfer.files ?? [])); },
  };

  return (
    <div className="upload">
    <form className="form" onSubmit={submit}>
      <div className="feed-slot">
        <span aria-hidden="true">↓</span>
        <p>{t("upload.feed")}</p>
      </div>
      <div className="field field--file">
        <label className="field__label" htmlFor={fileId}>
          {t("upload.file")}
        </label>
        {chosen.length === 0 ? (
          <div className={`dropzone${dragOver ? " dropzone--active" : ""}`} onClick={pick} {...dropTarget}>
            <input
              id={fileId}
              ref={fileInputRef}
              type="file"
              className="sr-only"
              accept=".csv,.xlsx,.xlsm,.xls"
              multiple={many}
              aria-describedby={hintId}
              onClick={(event) => event.stopPropagation()}
              onChange={(event) => {
                add(Array.from(event.target.files ?? []));
                event.target.value = "";
              }}
            />
            {dragOver ? (
              <p className="dropzone__main dropzone__main--active">{t("upload.dropActive")}</p>
            ) : (
              <div className="dropzone__prompt">
                <svg className="dropzone__glyph" width="32" height="32" viewBox="0 0 32 32" fill="none" stroke="currentColor"
                  strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M9 3h9l5 5v10H9z" />
                  <path d="M18 3v5h5" />
                  <path d="M4 23h24" />
                  <path d="M7 27h18" />
                </svg>
                <p className="dropzone__main">{t("upload.dragDrop")}</p>
                <div className="dropzone__sub">
                  <span className="dropzone__or">{t("upload.or")}</span>
                  <button type="button" className="button button--key button--choose" onClick={(event) => { event.stopPropagation(); pick(); }}>
                    {t("upload.choose")}
                  </button>
                </div>
                <span id={hintId} className="field__hint dropzone__hint">{t("upload.fileHint")}</span>
              </div>
            )}
          </div>
        ) : (
          <ul className={`file-tiles${dragOver ? " file-tiles--active" : ""}`} aria-label={t("upload.chosen")} {...dropTarget}>
            {chosen.map((item) => {
              const { stem, extension } = splitName(item.file.name);
              return (
                <li key={item.id} className="file-tile" title={item.file.name}>
                  <FileMark name={item.file.name} />
                  <span className="file-tile__text">
                    <span className="file-tile__name">{stem}</span>
                    <span className="file-tile__meta">
                      <span className="file-tile__extension">{extension}</span>
                      <span className="file-tile__size">{formatFileSize(item.file.size)}</span>
                    </span>
                  </span>
                  <button type="button" className="file-tile__remove" aria-label={t("upload.remove", { file: item.file.name })} onClick={() => remove(item.id)}>
                    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" aria-hidden="true">
                      <path d="M3 3l8 8M11 3l-8 8" />
                    </svg>
                  </button>
                </li>
              );
            })}
            <li className="file-tile file-tile--add">
              <input
                id={fileId}
                ref={fileInputRef}
                type="file"
                className="sr-only"
                tabIndex={-1}
                accept=".csv,.xlsx,.xlsm,.xls"
                multiple={many}
                aria-describedby={hintId}
                onChange={(event) => {
                  add(Array.from(event.target.files ?? []));
                  event.target.value = "";
                }}
              />
              <button ref={addKeyRef} type="button" className="file-tile__add" aria-describedby={hintId} onClick={pick}>
                <svg width="28" height="28" viewBox="0 0 28 28" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" aria-hidden="true">
                  <path d="M14 5v18M5 14h18" />
                </svg>
                <span>{dragOver ? t("upload.dropActive") : many ? t("upload.addFiles") : t("upload.changeFile")}</span>
              </button>
              <span id={hintId} className="sr-only">{t("upload.fileHint")}</span>
            </li>
          </ul>
        )}
      </div>
      {chosen.length > 0 && (
        <div className="file-list" role="group" aria-label={t("upload.suppliers")}>
          <div className="file-list__head" aria-hidden="true">
            <span>{t("upload.fileColumn")}</span>
            <span>{t("upload.supplierColumn")}</span>
            <span>{t("upload.sheet")}</span>
          </div>
          {chosen.map((item) => (
            <div key={item.id} className="file-list__row">
              <span className="file-list__file">{item.file.name}</span>
              <input
                aria-label={t("queue.supplier", { file: item.file.name })}
                value={item.supplierName}
                autoComplete="off"
                onChange={(event) => patch(item.id, { supplierName: event.target.value })}
              />
              <span className="file-list__sheet">
                {item.reading ? (
                  <TapeLoader size="small" text={t("upload.reading")} />
                ) : (item.sheets?.length ?? 0) > 1 ? (
                  <select aria-label={t("queue.sheet", { file: item.file.name })} value={item.sheet} onChange={(event) => patch(item.id, { sheet: event.target.value })}>
                    <option value="">{t("upload.sheetDefault")}</option>
                    {item.sheets!.map((name) => <option key={name} value={name}>{name}</option>)}
                  </select>
                ) : (
                  <span className="file-list__none">{t("upload.sheetDefault")}</span>
                )}
              </span>
              {item.problem && <p className="field__error file-list__problem" role="status">{item.problem}</p>}
            </div>
          ))}
          {chosen.length > 1 && <p className="hint">{t("queue.lede")}</p>}
        </div>
      )}
      {onListSamples && onLoadSample && <SamplePicker list={onListSamples} onChoose={chooseSample} disabled={busy} />}
      {notice && <p className="field__error" role="status">{notice}</p>}
      <div className="form__row">
        <label className="field">
          <span className="field__label">{t("upload.language")}</span>
          <select value={language} onChange={(event) => setManualLanguage(event.target.value as Language)}>
            <option value="en">{t("language.en")}</option>
            <option value="es">{t("language.es")}</option>
          </select>
        </label>
      </div>
      <div className="check">
        <input id={freshId} type="checkbox" checked={fresh} aria-describedby={freshHintId} onChange={(event) => setFresh(event.target.checked)} />
        <div>
          <label className="check__label" htmlFor={freshId}>{t("upload.fresh")}</label>
          <span id={freshHintId} className="field__hint">{t("upload.freshHint")}</span>
        </div>
      </div>
      <Button type="submit" variant="primary" disabled={!ready || busy} className={busy ? "button--busy" : undefined}>
        {busy ? <TapeLoader size="normal" text={t("upload.reading")} /> : t("upload.start")}
      </Button>
    </form>
    </div>
  );
}
