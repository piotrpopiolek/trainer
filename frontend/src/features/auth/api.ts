import { apiJson } from "@/lib/api";
import {
  disclaimerSchema,
  meSchema,
  type Disclaimer,
  type Me,
} from "@/lib/schemas";
import { newClientMutationId } from "@/lib/uuid";

export async function fetchMe(): Promise<Me> {
  const raw = await apiJson<unknown>("/api/auth/me");
  return meSchema.parse(raw);
}

export async function logout(): Promise<void> {
  await apiJson<{ ok: boolean }>("/api/auth/logout", { method: "POST" });
}

export async function logoutAll(): Promise<void> {
  await apiJson<{ ok: boolean }>("/api/auth/logout-all", { method: "POST" });
}


export async function fetchDisclaimer(locale = "pl-PL"): Promise<Disclaimer> {
  const raw = await apiJson<unknown>(
    `/api/legal/health-disclaimer?locale=${encodeURIComponent(locale)}`,
  );
  return disclaimerSchema.parse(raw);
}

export async function acceptDisclaimer(doc: Disclaimer): Promise<void> {
  await apiJson("/api/legal/acceptances", {
    method: "POST",
    body: JSON.stringify({
      schema_version: 1,
      payload: {
        schema_version: 1,
        client_mutation_id: newClientMutationId(),
        document_slug: doc.slug,
        document_version: doc.version,
        document_id: doc.document_id,
        accepted_locale: doc.locale,
        accepted_content_hash: doc.content_hash,
        accepted_at: new Date().toISOString(),
      },
    }),
  });
}

export async function completeOnboarding(input: {
  experience_level: "beginner" | "intermediate" | "advanced";
  training_days_per_week: number;
  goals: string[];
  anchor_weekday: 1 | 2;
  timezone: string;
}): Promise<void> {
  await apiJson("/api/onboarding/complete", {
    method: "POST",
    body: JSON.stringify({
      schema_version: 1,
      questionnaire: {
        schema_version: 1,
        experience_level: input.experience_level,
        training_days_per_week: input.training_days_per_week,
        goals: input.goals,
      },
      anchor_weekday: input.anchor_weekday,
      timezone: input.timezone,
    }),
  });
}
