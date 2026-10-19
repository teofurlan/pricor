import { useId, useRef, useState, type FormEvent } from "react";
import type { CreateImportInput, Language } from "../../api/types";
import { useI18n } from "../../i18n";
import { Button } from "../atoms/Button";
import { ExampleTape } from "../molecules/ExampleTape";

interface Props {
  busy: boolean;
  onSubmit(input: CreateImportInput): void;
  onInspectSheets?(file: File): Promise<string[]>;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function TapeLoader({
  size = "normal",
  text,
}: {
  size?: "normal" | "small";
  text: string;
}) {
  return (
    <div
      className={`tape-loader${size === "small" ? " tape-loader--small" : ""}`}
      role="status"
      aria-busy="true"
    >
      <span className="tape-loader__slot" aria-hidden="true">
        <span className="tape-loader__tape">
          <span className="tape-loader__line" />
          <span className="tape-loader__line" />
          {size === "normal" && <span className="tape-loader__line" />}
        </span>
      </span>
      <span className="tape-loader__text">{text}</span>
    </div>
  );
}

export function UploadForm({ busy, onSubmit, onInspectSheets }: Props) {
  const { t, language: interfaceLanguage } = useI18n();
  const [supplierName, setSupplierName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [availableSheets, setAvailableSheets] = useState<string[] | null>(null);
  const [inspectingSheets, setInspectingSheets] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [sheet, setSheet] = useState("");
  const [language, setLanguage] = useState<Language>(interfaceLanguage);
  const [fresh, setFresh] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const fileId = useId();
  const hintId = useId();
  const freshId = useId();
  const freshHintId = useId();

  const ready = supplierName.trim() !== "" && file !== null && !busy;

  function handleFile(selected: File | null) {
    setFile(selected);
    setSheet("");
    setAvailableSheets(null);
    if (selected && onInspectSheets) {
      setInspectingSheets(true);
      onInspectSheets(selected)
        .then((names) => setAvailableSheets(names))
        .catch(() => setAvailableSheets([]))
        .finally(() => setInspectingSheets(false));
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!file || !ready) return;
    onSubmit({ file, supplierName: supplierName.trim(), sheet, language, ...(fresh && { forceFirstImport: true }) });
  }

  return (
    <div className="workbench workbench--upload">
    <form className="form" onSubmit={submit}>
      <div className="feed-slot">
        <span aria-hidden="true">↓</span>
        <p>{t("upload.feed")}</p>
      </div>
      <label className="field">
        <span className="field__label">{t("upload.supplier")}</span>
        <input value={supplierName} onChange={(event) => setSupplierName(event.target.value)} autoComplete="off" />
      </label>
      <div className="field field--file">
        <label className="field__label" htmlFor={fileId}>
          {t("upload.file")}
        </label>
        <div
          className={`dropzone${dragOver ? " dropzone--active" : ""}`}
          onClick={() => fileInputRef.current?.click()}
          onDragOver={(event) => {
            event.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragOver(false);
            const dropped = event.dataTransfer.files?.[0];
            if (dropped) handleFile(dropped);
          }}
        >
          <input
            id={fileId}
            ref={fileInputRef}
            type="file"
            className="sr-only"
            accept=".csv,.xlsx,.xlsm,.xls"
            aria-describedby={hintId}
            onChange={(event) => handleFile(event.target.files?.[0] ?? null)}
          />
          {dragOver ? (
            <p className="dropzone__main dropzone__main--active">{t("upload.dropActive")}</p>
          ) : file ? (
            <div className="dropzone__selected" aria-live="polite">
              <div className="dropzone__fileinfo">
                <span className="dropzone__filename">{file.name}</span>
                <span className="dropzone__filesize">({formatFileSize(file.size)})</span>
              </div>
              <button
                type="button"
                className="button button--key button--choose"
                onClick={(event) => {
                  event.stopPropagation();
                  fileInputRef.current?.click();
                }}
              >
                {t("upload.changeFile")}
              </button>
              {inspectingSheets && (
                <TapeLoader size="small" text={t("upload.reading")} />
              )}
            </div>
          ) : (
            <div className="dropzone__prompt">
              <svg
                className="dropzone__glyph"
                width="32"
                height="32"
                viewBox="0 0 32 32"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.75"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <path d="M9 3h9l5 5v10H9z" />
                <path d="M18 3v5h5" />
                <path d="M4 23h24" />
                <path d="M7 27h18" />
              </svg>
              <p className="dropzone__main">{t("upload.dragDrop")}</p>
              <div className="dropzone__sub">
                <span className="dropzone__or">{t("upload.or")}</span>
                <button
                  type="button"
                  className="button button--key button--choose"
                  onClick={(event) => {
                    event.stopPropagation();
                    fileInputRef.current?.click();
                  }}
                >
                  {t("upload.choose")}
                </button>
              </div>
              <span id={hintId} className="field__hint dropzone__hint">
                {t("upload.fileHint")}
              </span>
            </div>
          )}
        </div>
      </div>
      <div className="form__row">
        {availableSheets && availableSheets.length > 1 && (
          <label className="field">
            <span className="field__label">{t("upload.sheet")}</span>
            <select value={sheet} onChange={(event) => setSheet(event.target.value)}>
              <option value="">{t("upload.sheetDefault")}</option>
              {availableSheets.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>
        )}
        <label className="field">
          <span className="field__label">{t("upload.language")}</span>
          <select value={language} onChange={(event) => setLanguage(event.target.value as Language)}>
            <option value="en">{t("language.en")}</option>
            <option value="es">{t("language.es")}</option>
          </select>
        </label>
      </div>
      <div className="check">
        <input
          id={freshId}
          type="checkbox"
          checked={fresh}
          aria-describedby={freshHintId}
          onChange={(event) => setFresh(event.target.checked)}
        />
        <div>
          <label className="check__label" htmlFor={freshId}>
            {t("upload.fresh")}
          </label>
          <span id={freshHintId} className="field__hint">
            {t("upload.freshHint")}
          </span>
        </div>
      </div>
      <Button
        type="submit"
        variant="primary"
        disabled={!ready || busy}
        className={busy ? "button--busy" : undefined}
      >
        {busy ? (
          <TapeLoader size="normal" text={t("upload.reading")} />
        ) : (
          t("upload.start")
        )}
      </Button>
    </form>
    <ExampleTape />
    </div>
  );
}
