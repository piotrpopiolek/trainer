import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { Button, Page } from "@/components/ui";
import { logout, logoutAll } from "@/features/auth/api";
import { useAuthStore } from "@/stores/authStore";

export function SettingsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const me = useAuthStore((s) => s.me);
  const clear = useAuthStore((s) => s.clear);
  const qc = useQueryClient();

  const logoutMut = useMutation({
    mutationFn: logout,
    onSuccess: async () => {
      clear();
      await qc.clear();
      navigate("/login", { replace: true });
    },
  });

  const logoutAllMut = useMutation({
    mutationFn: logoutAll,
    onSuccess: async () => {
      clear();
      await qc.clear();
      navigate("/login", { replace: true });
    },
  });

  return (
    <Page title={t("settings.title")}>
      <div className="rounded-xl border border-slate-200 bg-white/80 px-4 py-3 text-sm">
        <p className="font-medium">{me?.display_name || me?.email || t("settings.user")}</p>
        <p className="text-slate-500">{me?.email}</p>
        <p className="text-slate-500">
          {me?.locale} · {me?.timezone}
        </p>
      </div>
      <div className="flex flex-col gap-2">
        <Button
          variant="secondary"
          disabled={logoutMut.isPending}
          onClick={() => logoutMut.mutate()}
        >
          {t("settings.logout")}
        </Button>
        <Button
          variant="danger"
          disabled={logoutAllMut.isPending}
          onClick={() => logoutAllMut.mutate()}
        >
          {t("settings.logoutAll")}
        </Button>
      </div>
    </Page>
  );
}
