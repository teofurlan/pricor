import { useId, useState, type FormEvent } from "react";
import type { CreateImportInput, Language } from "../../api/types";
import { useI18n } from "../../i18n";
import { Button } from "../atoms/Button";

interface Props {
  busy: boolean;
  onSubmit(input: CreateImportInput): void;
}

export function UploadForm({ busy, onSubmit }: Props) {
  const { t, language: interfaceLanguage } = useI18n();
  const [supplierName, setSupplierName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [sheet, setSheet] = useState("");
  const [language, setLanguage] = useState<Language>(interfaceLanguage);
  const [fresh, setFresh] = useState(false);
  const fileId = useId();
  const hintId = useId();
  const freshId = useId();
  const freshHintId = useId();

  const ready = supplierName.trim() !== "" && file !== null && !busy;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!file || !ready) return;
    onSubmit({ file, supplierName: supplierName.trim(), sheet, language, ...(fresh && { forceFirstImport: true }) });
  }

  return (
    <form className="form" onSubmit={submit}>
      <label className="field">
        <span className="field__label">{t("upload.supplier")}</span>
        <input value={supplierName} onChange={(event) => setSupplierName(event.target.value)} autoComplete="off" />
      </label>
      <div className="field">
        <label className="field__label" htmlFor={fileId}>
          {t("upload.file")}
        </label>
        <input
          id={fileId}
          type="file"
          accept=".csv,.xlsx,.xlsm,.xls"
          aria-describedby={hintId}
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
        />
        <span id={hintId} className="field__hint">
          {t("upload.fileHint")}
        </span>
      </div>
      <div className="form__row">
        <label className="field">
          <span className="field__label">{t("upload.sheet")}</span>
          <input value={sheet} onChange={(event) => setSheet(event.target.value)} autoComplete="off" />
        </label>
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
      <Button type="submit" variant="primary" disabled={!ready}>
        {busy ? t("upload.reading") : t("upload.start")}
      </Button>
    </form>
  );
}
