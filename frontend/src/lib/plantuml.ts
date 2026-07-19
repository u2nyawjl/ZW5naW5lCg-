// PlantUML en cliente con el formato hex (~h) de plantuml.com: sin librería de deflate.
//
// OJO a la privacidad: renderizar con PlantUML manda el TEXTO del diagrama al
// servidor. Con el público, un diagrama con nombres reales de compañeros o con la
// estructura interna del proyecto sale de aquí. Para eso está VITE_PLANTUML_SERVER:
// levanta uno propio (docker run -d -p 8080:8080 plantuml/plantuml-server) y apunta
// ahí. Si el diagrama es sensible, usa ```mermaid, que se dibuja en el navegador.
const SERVER = (import.meta.env.VITE_PLANTUML_SERVER || "https://www.plantuml.com/plantuml")
  .replace(/\/+$/, "");

export function plantumlUrl(src: string): string {
  const hex = Array.from(new TextEncoder().encode(src.trim()))
    .map((b) => b.toString(16).padStart(2, "0")).join("");
  return `${SERVER}/svg/~h${hex}`;
}

// Reemplaza bloques ```plantuml por imágenes markdown, para renderizarlos en notas.
// Mermaid NO se toca aquí: necesita dibujarse contra el DOM, así que va como
// componente en <Mermaid/> (ver MD_COMPONENTS en NoteView).
export function withDiagrams(md: string): string {
  return md.replace(/```(?:plantuml|puml)\s*([\s\S]*?)```/g,
    (_, code) => `\n![diagrama](${plantumlUrl(code)})\n`);
}
