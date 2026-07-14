import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Página de proyecto en GitHub Pages: sirve bajo /<repo>/.
// El nombre del repo del agente es ZW5naW5lCg- (base64 de "engine").
export default defineConfig({
  plugins: [react()],
  base: "/ZW5naW5lCg-/",
  build: { outDir: "dist" },
});
