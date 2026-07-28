import { create } from "zustand";

import type { Me } from "@/lib/schemas";

type AuthState = {
  me: Me | null;
  setMe: (me: Me | null) => void;
  csrfToken: string | null;
  setCsrfToken: (token: string | null) => void;
  clear: () => void;
};

export const useAuthStore = create<AuthState>((set) => ({
  me: null,
  csrfToken: null,
  setMe: (me) => set({ me, csrfToken: me?.csrf_token ?? null }),
  setCsrfToken: (csrfToken) => set({ csrfToken }),
  clear: () => set({ me: null, csrfToken: null }),
}));
