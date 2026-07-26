import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { apiFetch } from "@/lib/api";

type HealthResponse = { status: string };

async function fetchHealth(): Promise<HealthResponse> {
  const res = await apiFetch("/api/health");
  if (!res.ok) {
    throw new Error(`health_${res.status}`);
  }
  return res.json() as Promise<HealthResponse>;
}

export function App() {
  const { t } = useTranslation();
  const health = useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
    retry: false,
  });

  return (
    <main className="mx-auto flex min-h-screen max-w-lg flex-col justify-center gap-4 px-6 py-12">
      <h1 className="text-3xl font-semibold tracking-tight">{t("app.name")}</h1>
      <p className="text-slate-600">{t("app.tagline")}</p>
      <section aria-live="polite" className="text-sm text-slate-700">
        <p className="font-medium">{t("shell.apiStatus")}</p>
        {health.isLoading && <p>{t("shell.loading")}</p>}
        {health.isSuccess && health.data.status === "ok" && <p>{t("shell.apiOk")}</p>}
        {health.isError && <p>{t("shell.apiDown")}</p>}
      </section>
    </main>
  );
}
