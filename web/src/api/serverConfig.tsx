import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import type { ApiClient } from "./client";
import type { ServerConfig } from "./types";

export interface ServerConfigContextValue {
  config: ServerConfig | null;
  hosted: boolean;
  /** False only while the server config is still being fetched. */
  loaded: boolean;
}

const ServerConfigContext = createContext<ServerConfigContextValue>({
  config: null,
  hosted: false,
  loaded: true,
});

export function isHosted(config: ServerConfig | null | undefined): boolean {
  if (!config) return false;
  return !(config.model_provider === "ollama" && config.demo === false);
}

export function ServerConfigProvider({
  api,
  initialConfig = null,
  hosted: hostedProp,
  children,
}: {
  api?: ApiClient;
  initialConfig?: ServerConfig | null;
  hosted?: boolean;
  children: ReactNode;
}) {
  const [config, setConfig] = useState<ServerConfig | null>(initialConfig);
  const [settled, setSettled] = useState(false);

  useEffect(() => {
    if (!api || typeof api.config !== "function") return;
    let active = true;
    api.config()
      .then((cfg) => {
        if (active) {
          setConfig(cfg);
          setSettled(true);
        }
      })
      .catch(() => {
        // Fall back to local on failure
        if (active) setSettled(true);
      });
    return () => {
      active = false;
    };
  }, [api]);

  const hosted = hostedProp !== undefined ? hostedProp : isHosted(config);
  const waiting = !!api && typeof api.config === "function" && !settled && initialConfig === null;
  const value = useMemo(() => ({ config, hosted, loaded: !waiting }), [config, hosted, waiting]);

  return <ServerConfigContext.Provider value={value}>{children}</ServerConfigContext.Provider>;
}

export function useServerConfig(): ServerConfigContextValue {
  return useContext(ServerConfigContext);
}
