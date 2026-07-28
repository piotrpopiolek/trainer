import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { Button, Page, Select } from "@/components/ui";
import { completeOnboarding, fetchMe } from "@/features/auth/api";
import { ApiError, googleStartUrl } from "@/lib/api";
import { localTimezone } from "@/lib/dates";
import { errorCodeToI18nKey } from "@/lib/errors";
import { useAuthStore } from "@/stores/authStore";

export function LoginPage() {
  const { t } = useTranslation();
  const [params] = useSearchParams();
  const error = params.get("error");

  return (
    <main className="mx-auto flex min-h-screen max-w-lg flex-col justify-center gap-6 px-6 py-12">
      <div>
        <p className="text-sm font-semibold uppercase tracking-[0.2em] text-teal-800">
          {t("app.name")}
        </p>
        <h1 className="font-display mt-2 text-4xl font-semibold tracking-tight text-slate-900">
          {t("login.title")}
        </h1>
        <p className="mt-3 text-slate-600">{t("login.subtitle")}</p>
      </div>
      {error ? (
        <p className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-800" role="alert">
          {t(errorCodeToI18nKey(error))}
        </p>
      ) : null}
      <Button
        className="w-full"
        onClick={() => {
          window.location.assign(googleStartUrl());
        }}
      >
        {t("login.google")}
      </Button>
    </main>
  );
}

export function OnboardingPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const setMe = useAuthStore((s) => s.setMe);
  const qc = useQueryClient();
  const [experience, setExperience] = useState<"beginner" | "intermediate" | "advanced">(
    "beginner",
  );
  const [days, setDays] = useState(3);
  const [anchor, setAnchor] = useState<1 | 2>(1);
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      completeOnboarding({
        experience_level: experience,
        training_days_per_week: days,
        goals: ["strength"],
        anchor_weekday: anchor,
        timezone: localTimezone(),
      }),
    onSuccess: async () => {
      const me = await fetchMe();
      setMe(me);
      await qc.invalidateQueries({ queryKey: ["me"] });
      navigate("/legal", { replace: true });
    },
    onError: (err) => {
      if (err instanceof ApiError) {
        setError(t(errorCodeToI18nKey(err.errorCode)));
      } else {
        setError(t("errors.generic"));
      }
    },
  });

  return (
    <Page title={t("onboarding.title")}>
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          setError(null);
          mutation.mutate();
        }}
      >
        <Select
          label={t("onboarding.experience")}
          value={experience}
          onChange={(e) =>
            setExperience(e.target.value as "beginner" | "intermediate" | "advanced")
          }
        >
          <option value="beginner">{t("onboarding.expBeginner")}</option>
          <option value="intermediate">{t("onboarding.expIntermediate")}</option>
          <option value="advanced">{t("onboarding.expAdvanced")}</option>
        </Select>
        <Select
          label={t("onboarding.days")}
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
        >
          {[2, 3, 4, 5, 6].map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </Select>
        <Select
          label={t("onboarding.split")}
          value={anchor}
          onChange={(e) => setAnchor(Number(e.target.value) as 1 | 2)}
        >
          <option value={1}>{t("onboarding.splitMon")}</option>
          <option value={2}>{t("onboarding.splitTue")}</option>
        </Select>
        {error ? (
          <p className="text-sm text-rose-700" role="alert">
            {error}
          </p>
        ) : null}
        <Button type="submit" disabled={mutation.isPending} className="w-full">
          {mutation.isPending ? t("shell.loading") : t("onboarding.submit")}
        </Button>
      </form>
    </Page>
  );
}
