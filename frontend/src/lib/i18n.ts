import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import plPL from "@/locales/pl-PL/common.json";

void i18n.use(initReactI18next).init({
  resources: {
    "pl-PL": { common: plPL },
  },
  lng: "pl-PL",
  fallbackLng: "pl-PL",
  defaultNS: "common",
  interpolation: { escapeValue: false },
});

export default i18n;
