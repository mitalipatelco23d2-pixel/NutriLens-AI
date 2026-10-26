import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";
import prettier from "eslint-config-prettier/flat";

export default defineConfig([
  ...nextVitals,
  ...nextTs,
  prettier,
  {
    rules: {
      "@next/next/no-img-element": "off",
    },
  },
  globalIgnores([
    ".next/**",
    ".open-next/**",
    ".model-cache/**",
    ".venv/**",
    ".venv-r3-paddle/**",
    "out/**",
    "build/**",
    "apps/mobile/**",
    "data/**",
    "outputs/**",
    "next-env.d.ts",
  ]),
]);
