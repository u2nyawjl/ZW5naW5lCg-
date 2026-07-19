/// <reference types="vite/client" />

// Servidor de PlantUML. Vacío = el público (plantuml.com), al que viaja el texto
// del diagrama. Apúntalo a uno propio si los diagramas llevan datos reales.
interface ImportMetaEnv {
  readonly VITE_PLANTUML_SERVER?: string;
}
interface ImportMeta {
  readonly env: ImportMetaEnv;
}

// mammoth no publica tipos para su build de navegador (el que no arrastra Node).
declare module "mammoth/mammoth.browser" {
  const mammoth: {
    convertToHtml(input: { arrayBuffer: ArrayBuffer }): Promise<{ value: string; messages: unknown[] }>;
  };
  export default mammoth;
}
