/// <reference types="vite/client" />

// Servidor de PlantUML. Vacío = el público (plantuml.com), al que viaja el texto
// del diagrama. Apúntalo a uno propio si los diagramas llevan datos reales.
interface ImportMetaEnv {
  readonly VITE_PLANTUML_SERVER?: string;
}
interface ImportMeta {
  readonly env: ImportMetaEnv;
}
