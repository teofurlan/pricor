import { useCallback, useEffect, useRef, useState } from "react";
import { useI18n } from "../../i18n";
import { Button } from "../atoms/Button";

const GSI_SCRIPT_SRC = "https://accounts.google.com/gsi/client";

interface GoogleIdentityApi {
  initialize(options: {
    client_id: string;
    callback: (response: { credential?: string }) => void;
  }): void;
  prompt(): void;
  renderButton?(parent: HTMLElement, options: Record<string, unknown>): void;
}

interface GoogleWindow extends Window {
  google?: { accounts?: { id?: GoogleIdentityApi } };
  __pricorGooglePrompt?: (cb: (credential: string) => void) => void;
}

export interface WorkspacePanelProps {
  link?: string;
  account?: { email: string } | null;
  googleClientId?: string | null;
  busy?: boolean;
  onGoogleCredential?: (credential: string) => void | Promise<void>;
  onUnlinkGoogle?: () => void | Promise<void>;
}

/** Optional Google account bar; without Google auth configured, the workspace cookie works silently. */
export function WorkspacePanel({
  account = null,
  googleClientId = null,
  busy = false,
  onGoogleCredential,
  onUnlinkGoogle,
}: WorkspacePanelProps) {
  const { t } = useI18n();
  const [gisRendered, setGisRendered] = useState(false);
  const gisButtonRef = useRef<HTMLDivElement>(null);
  const onCredentialRef = useRef(onGoogleCredential);
  onCredentialRef.current = onGoogleCredential;

  const initGis = useCallback((clientId: string): boolean => {
    const gsi = (window as GoogleWindow).google?.accounts?.id;
    if (!gsi) return false;
    gsi.initialize({
      client_id: clientId,
      callback: (response) => {
        if (response.credential && onCredentialRef.current) {
          void onCredentialRef.current(response.credential);
        }
      },
    });
    if (gisButtonRef.current && typeof gsi.renderButton === "function") {
      gisButtonRef.current.innerHTML = "";
      gsi.renderButton(gisButtonRef.current, { theme: "outline", size: "medium" });
      setGisRendered(true);
    }
    return true;
  }, []);

  useEffect(() => {
    if (account?.email) {
      setGisRendered(false);
      return;
    }
    if (!googleClientId || !onGoogleCredential) return;
    if (initGis(googleClientId)) return;

    let active = true;
    const onLoad = () => {
      if (active) initGis(googleClientId);
    };

    const existing = document.querySelector<HTMLScriptElement>(`script[src="${GSI_SCRIPT_SRC}"]`);
    if (existing) {
      existing.addEventListener("load", onLoad);
      return () => {
        active = false;
        existing.removeEventListener("load", onLoad);
      };
    }

    const script = document.createElement("script");
    script.src = GSI_SCRIPT_SRC;
    script.async = true;
    script.defer = true;
    script.addEventListener("load", onLoad);
    script.addEventListener("error", () => undefined);
    document.head.appendChild(script);
    return () => {
      active = false;
      script.removeEventListener("load", onLoad);
    };
  }, [googleClientId, account?.email, onGoogleCredential, initGis]);

  function startGoogleSignIn() {
    const win = window as GoogleWindow;
    if (typeof win.__pricorGooglePrompt === "function") {
      win.__pricorGooglePrompt((cred) => {
        if (onCredentialRef.current) void onCredentialRef.current(cred);
      });
      return;
    }
    if (googleClientId && initGis(googleClientId)) {
      win.google?.accounts?.id?.prompt();
    }
  }

  if (account?.email) {
    return (
      <section className="workspace" aria-label={t("workspace.title")}>
        <p className="workspace__account-label">
          {t("workspace.google.linked", { email: account.email })}
        </p>
        {onUnlinkGoogle && (
          <div className="workspace__actions">
            <Button variant="quiet" disabled={busy} onClick={() => void onUnlinkGoogle()}>
              {t("workspace.google.unlink")}
            </Button>
          </div>
        )}
      </section>
    );
  }

  if (!googleClientId || !onGoogleCredential) {
    return null;
  }

  return (
    <section className="workspace" aria-label={t("workspace.title")}>
      <p className="workspace__body">{t("workspace.body")}</p>
      <div className="workspace__actions">
        <div ref={gisButtonRef} className="workspace__gis-slot" />
        {!gisRendered && (
          <Button variant="quiet" disabled={busy} onClick={startGoogleSignIn}>
            {t("workspace.google.signIn")}
          </Button>
        )}
      </div>
    </section>
  );
}
