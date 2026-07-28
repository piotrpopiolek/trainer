import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { Button, Page } from "@/components/ui";
import { acceptDisclaimer, fetchDisclaimer, fetchMe } from "@/features/auth/api";
import { ApiError } from "@/lib/api";
import { errorCodeToI18nKey } from "@/lib/errors";
import { useAuthStore } from "@/stores/authStore";

export function LegalPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const setMe = useAuthStore((s) => s.setMe);
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["legal", "health-disclaimer"],
    queryFn: () => fetchDisclaimer("pl-PL"),
  });

  const mutation = useMutation({
    mutationFn: async () => {
      if (!q.data) throw new Error("missing_disclaimer");
      await acceptDisclaimer(q.data);
      const me = await fetchMe();
      setMe(me);
      await qc.invalidateQueries({ queryKey: ["me"] });
    },
    onSuccess: () => navigate("/", { replace: true }),
  });

  if (q.isLoading) {
    return <Page title={t("legal.title")}>{t("shell.loading")}</Page>;
  }

  if (q.isError || !q.data) {
    const code = q.error instanceof ApiError ? q.error.errorCode : "generic";
    return (
      <Page title={t("legal.title")}>
        <p className="text-rose-700">{t(errorCodeToI18nKey(code))}</p>
      </Page>
    );
  }

  return (
    <Page title={q.data.title || t("legal.title")}>
      <article className="prose prose-sm max-w-none whitespace-pre-wrap rounded-xl border border-slate-200 bg-white/80 p-4 text-slate-800">
        {q.data.body}
      </article>
      {mutation.isError ? (
        <p className="text-sm text-rose-700" role="alert">
          {mutation.error instanceof ApiError
            ? t(errorCodeToI18nKey(mutation.error.errorCode))
            : t("errors.generic")}
        </p>
      ) : null}
      <Button
        className="w-full"
        disabled={mutation.isPending}
        onClick={() => mutation.mutate()}
      >
        {t("legal.accept")}
      </Button>
    </Page>
  );
}
