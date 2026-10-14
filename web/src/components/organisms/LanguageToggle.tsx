import { useI18n } from "../../i18n";

export function LanguageToggle() {
  const { language, setLanguage, t } = useI18n();
  return (
    <div className="lang" role="group" aria-label={t("language.label")}>
      {(["en", "es"] as const).map((code) => (
        <button
          key={code}
          type="button"
          className="lang__option"
          aria-pressed={language === code}
          onClick={() => setLanguage(code)}
        >
          {code.toUpperCase()}
        </button>
      ))}
    </div>
  );
}
