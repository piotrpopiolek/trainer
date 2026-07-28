import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "@/components/AppShell";
import { LegalPage } from "@/features/auth/LegalPage";
import { LoginPage, OnboardingPage } from "@/features/auth/pages";
import { RequireAuth } from "@/features/auth/RequireAuth";
import { MeasurementsPage } from "@/features/measurements/MeasurementsPage";
import { ProgressPage } from "@/features/progress/ProgressPage";
import { SatellitesPage } from "@/features/satellites/SatellitesPage";
import { SettingsPage } from "@/features/settings/SettingsPage";
import { TodayPage } from "@/features/today/TodayPage";

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route path="/onboarding" element={<OnboardingPage />} />
        <Route path="/legal" element={<LegalPage />} />
        <Route element={<AppShell />}>
          <Route index element={<TodayPage />} />
          <Route path="/progress" element={<ProgressPage />} />
          <Route path="/satellites" element={<SatellitesPage />} />
          <Route path="/measurements" element={<MeasurementsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

/** Production entry uses BrowserRouter in main.tsx; tests inject MemoryRouter. */
export function App() {
  return <AppRoutes />;
}
