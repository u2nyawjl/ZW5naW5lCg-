import { useEffect, useState } from "react";

// Mermaid dibuja en el navegador: a diferencia de PlantUML, el diagrama nunca sale
// de esta máquina. Por eso es el que conviene cuando el diagrama lleva nombres
// reales de compañeros o estructura interna del proyecto.
//
// Se carga con import() dinámico y no arriba del todo: son ~1 MB y la inmensa
// mayoría de las notas no llevan diagrama. Así solo lo paga quien abre una que sí.
type MermaidApi = typeof import("mermaid").default;
let loading: Promise<MermaidApi> | null = null;

function getMermaid(): Promise<MermaidApi> {
  if (!loading) {
    loading = import("mermaid").then((m) => {
      m.default.initialize({
        startOnLoad: false,
        theme: "dark",
        // Los diagramas pueden venir de un correo, y un correo es DATOS, no código:
        // "strict" desactiva el HTML incrustado en las etiquetas.
        securityLevel: "strict",
        fontFamily: "inherit",
      });
      return m.default;
    });
  }
  return loading;
}

let seq = 0;

export function Mermaid({ code }: { code: string }) {
  const [svg, setSvg] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => {
    let alive = true;
    getMermaid()
      .then((mermaid) => mermaid.render(`mmd-${++seq}`, code.trim()))
      .then((r) => { if (alive) { setSvg(r.svg); setErr(""); } })
      .catch((e) => { if (alive) { setSvg(""); setErr(String(e?.message || e)); } });
    return () => { alive = false; };
  }, [code]);

  // Un diagrama mal escrito no debe tragarse la nota entera: se muestra el error
  // junto al código para poder arreglarlo.
  if (err) {
    return (
      <div className="diagram-error">
        <strong>Mermaid no pudo dibujar esto</strong>
        <pre>{err}</pre>
        <pre>{code.trim()}</pre>
      </div>
    );
  }
  if (!svg) return <div className="diagram-loading">dibujando…</div>;
  return <div className="mermaid-out" dangerouslySetInnerHTML={{ __html: svg }} />;
}
