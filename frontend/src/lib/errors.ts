/** Map stable API error_code → i18n key under errors.* */

const KNOWN: Record<string, string> = {
  legal_required: "errors.legalRequired",
  enrollment_required: "errors.enrollmentRequired",
  onboarding_already_completed: "errors.onboardingDone",
  satellite_limit_reached: "errors.satelliteLimit",
  duplicate_exercise_same_day: "errors.duplicateExercise",
  session_immutable_after_evaluate: "errors.sessionImmutable",
  session_date_immutable: "errors.sessionDateImmutable",
  batch_too_large: "errors.batchTooLarge",
  email_not_verified: "errors.emailNotVerified",
  oauth_state_invalid: "errors.oauthState",
  unauthorized: "errors.unauthorized",
  not_found: "errors.notFound",
  nothing_to_update: "errors.nothingToUpdate",
};

export function errorCodeToI18nKey(errorCode: string): string {
  return KNOWN[errorCode] ?? "errors.generic";
}
