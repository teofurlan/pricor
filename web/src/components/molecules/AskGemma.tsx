import { useId, useState, type FormEvent } from "react";
import { useServerConfig } from "../../api/serverConfig";
import type { AskTurn } from "../../api/types";
import { useI18n } from "../../i18n";
import { Button } from "../atoms/Button";

interface Props {
  thread: AskTurn[];
  pending: boolean;
  error: string | null;
  onAsk(message: string): void;
}

/** A side conversation about one question. Gemma may explain or suggest; the keys still decide. */
export function AskGemma({ thread, pending, error, onAsk }: Props) {
  const { t } = useI18n();
  const { hosted } = useServerConfig();
  const [message, setMessage] = useState("");
  const fieldId = useId();
  const text = message.trim();

  function submit(event: FormEvent) {
    event.preventDefault();
    if (text === "" || pending) return;
    onAsk(text);
    setMessage("");
  }

  return (
    <div className="ask">
      {thread.length > 0 && (
        <ol className="ask__thread">
          {thread.map((turn, index) => (
            <li key={index} className={`ask__turn ask__turn--${turn.role}`}>
              <span className="ask__speaker">{turn.role === "user" ? t("ask.you") : t("ask.assistant")}</span>
              <p className="ask__text">{turn.text}</p>
            </li>
          ))}
        </ol>
      )}
      <form className="ask__form" onSubmit={submit}>
        <label htmlFor={fieldId} className="ask__label">{t("ask.label")}</label>
        <div className="ask__row">
          <input id={fieldId} value={message} maxLength={500} placeholder={t("ask.placeholder")} onChange={(event) => setMessage(event.target.value)} />
          <Button type="submit" disabled={text === ""} loading={pending}>{t("ask.send")}</Button>
        </div>
      </form>
      {pending && <p className="hint">{t(hosted ? "ask.waiting.hosted" : "ask.waiting")}</p>}
      {error && <p className="ask__error" role="alert">{error}</p>}
    </div>
  );
}
