import { create } from "zustand";

import type { Me } from "@/lib/schemas";
import { meSchema } from "@/lib/schemas";

const ME_CACHE_KEY = "trainer.me.v1";

function cacheMe(me: Me | null): void {
  try {
    if (me) sessionStorage.setItem(ME_CACHE_KEY, JSON.stringify(me));
    else sessionStorage.removeItem(ME_CACHE_KEY);
  } catch {
    // private mode / quota — ignore
  }
}

export function readCachedMe(): Me | null {
  try {
    const raw = sessionStorage.getItem(ME_CACHE_KEY);
    if (!raw) return null;
    return meSchema.parse(JSON.parse(raw) as unknown);
  } catch {
    return null;
  }
}

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
  setMe: (me) => {
    cacheMe(me);
    set({ me, csrfToken: me?.csrf_token ?? null });
  },
  setCsrfToken: (csrfToken) => set({ csrfToken }),
  clear: () => {
    cacheMe(null);
    set({ me: null, csrfToken: null });
  },
}));
