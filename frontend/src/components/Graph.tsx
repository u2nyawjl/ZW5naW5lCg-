import { useEffect, useRef } from "react";
import * as d3 from "d3";

export interface GraphNode { id: string; group: number; }
export interface GraphLink { source: string; target: string; }

// Colores de estrellas reales por tipo espectral: azul, cian, blanco, ámbar, rojo, verde.
const COLORS = ["#8ec5ff", "#5fdcff", "#ffffff", "#ffd479", "#ff7a99", "#5ee6a8"];

// Grafo de conocimiento: nodos = notas de la bóveda, aristas = wikilinks [[...]].
export function Graph({ nodes, links }: { nodes: GraphNode[]; links: GraphLink[] }) {
  const ref = useRef<SVGSVGElement>(null);

  useEffect(() => {
    if (!ref.current || nodes.length === 0) return;
    const svg = d3.select(ref.current);
    svg.selectAll("*").remove();

    const width = ref.current.clientWidth;
    const height = ref.current.clientHeight;

    const sim = d3
      .forceSimulation(nodes as d3.SimulationNodeDatum[])
      .force("link", d3.forceLink(links).id((d: any) => d.id).distance(70))
      .force("charge", d3.forceManyBody().strength(-180))
      .force("center", d3.forceCenter(width / 2, height / 2));

    const g = svg.append("g");
    svg.call(
      d3.zoom<SVGSVGElement, unknown>().on("zoom", (e) => g.attr("transform", e.transform)) as any
    );

    const link = g.append("g").selectAll("line").data(links).enter().append("line")
      .attr("stroke", "rgba(157,139,255,0.28)");

    const node = g.append("g").selectAll("g").data(nodes).enter().append("g")
      .call(d3.drag<any, any>()
        .on("start", (e, d) => { if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
        .on("drag", (e, d) => { d.fx = e.x; d.fy = e.y; })
        .on("end", (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }));

    // Glow por-nodo con color explícito (sin depender de CSS ni currentColor).
    node.append("circle").attr("r", 6)
      .attr("fill", (d) => COLORS[d.group % COLORS.length])
      .style("filter", (d) => {
        const c = COLORS[d.group % COLORS.length];
        return `drop-shadow(0 0 4px ${c}) drop-shadow(0 0 10px ${c})`;
      });
    // Texto blanco con contorno oscuro (paint-order) para que resalte sobre el cielo.
    node.append("text").attr("dx", 10).attr("dy", "0.35em").text((d) => d.id)
      .attr("fill", "#ffffff")
      .attr("stroke", "#05060f").attr("stroke-width", 3)
      .attr("paint-order", "stroke")
      .attr("font-size", 10);

    sim.on("tick", () => {
      link.attr("x1", (d: any) => d.source.x).attr("y1", (d: any) => d.source.y)
        .attr("x2", (d: any) => d.target.x).attr("y2", (d: any) => d.target.y);
      node.attr("transform", (d: any) => `translate(${d.x},${d.y})`);
    });

    return () => { sim.stop(); };
  }, [nodes, links]);

  return <svg ref={ref} style={{ width: "100%", height: "100%" }} />;
}
