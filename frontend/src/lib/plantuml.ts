// PlantUML en cliente con el formato hex (~h) de plantuml.com: sin librería de deflate.
export function plantumlUrl(src: string): string {
  const hex = Array.from(new TextEncoder().encode(src.trim()))
    .map((b) => b.toString(16).padStart(2, "0")).join("");
  return `https://www.plantuml.com/plantuml/svg/~h${hex}`;
}

// Reemplaza bloques ```plantuml por imágenes markdown, para renderizarlos en notas.
export function withDiagrams(md: string): string {
  return md.replace(/```(?:plantuml|puml)\s*([\s\S]*?)```/g,
    (_, code) => `\n![diagrama](${plantumlUrl(code)})\n`);
}
