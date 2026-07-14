import { useEffect, useRef } from "react";
import * as d3 from "d3";

export interface GraphNode { id: string; group: number; }
export interface GraphLink { source: string; target: string; }

// Halos de color por tipo espectral. El núcleo de la estrella es blanco.
const GLOW = ["#8ec5ff", "#5fdcff", "#c9b3ff", "#ffd479", "#ff7a99", "#7ef0d0"];

// Estrella de 4 puntas (destello) centrada en el origen.
function sparkle(r: number): string {
  const o = r * 2.2, i = r * 0.34;
  return `M0,${-o} L${i},${-i} L${o},0 L${i},${i} L0,${o} L${-i},${i} L${-o},0 L${-i},${-i} Z`;
}

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
      .force("link", d3.forceLink(links).id((d: any) => d.id).distance(90).strength(0.4))
      .force("charge", d3.forceManyBody().strength(-140))
      .force("collide", d3.forceCollide(26))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .alphaDecay(0.05)   // asienta rápido y se detiene: no vuelve a "explotar"
      .alphaMin(0.02);

    const g = svg.append("g");
    svg.call(
      d3.zoom<SVGSVGElement, unknown>().on("zoom", (e) => g.attr("transform", e.transform)) as any
    );

    // Enlaces de energía blanca (blanco con halo, finos).
    const link = g.append("g").selectAll("line").data(links).enter().append("line")
      .attr("stroke", "rgba(255,255,255,0.55)")
      .attr("stroke-width", 1)
      .style("filter", "drop-shadow(0 0 3px rgba(255,255,255,0.7))");

    const node = g.append("g").selectAll("g").data(nodes).enter().append("g")
      .style("cursor", "grab")
      .call(d3.drag<any, any>()
        .on("start", (e, d) => { if (!e.active) sim.alphaTarget(0.15).restart(); d.fx = d.x; d.fy = d.y; })
        .on("drag", (e, d) => { d.fx = e.x; d.fy = e.y; })
        .on("end", (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }));

    // Halo suave de color detrás de cada estrella.
    node.append("circle").attr("r", 11)
      .attr("fill", (d) => GLOW[d.group % GLOW.length])
      .style("opacity", 0.18)
      .style("filter", "blur(4px)");

    // Núcleo: destello blanco con glow en el color de la estrella.
    node.append("path").attr("d", sparkle(6))
      .attr("fill", "#ffffff")
      .style("filter", (d) => {
        const c = GLOW[d.group % GLOW.length];
        return `drop-shadow(0 0 3px ${c}) drop-shadow(0 0 8px ${c})`;
      });

    node.append("text").attr("dx", 14).attr("dy", "0.35em").text((d) => d.id)
      .attr("fill", "#ffffff").attr("stroke", "#05060f").attr("stroke-width", 3)
      .attr("paint-order", "stroke").attr("font-size", 10);

    sim.on("tick", () => {
      link.attr("x1", (d: any) => d.source.x).attr("y1", (d: any) => d.source.y)
        .attr("x2", (d: any) => d.target.x).attr("y2", (d: any) => d.target.y);
      node.attr("transform", (d: any) => `translate(${d.x},${d.y})`);
    });

    return () => { sim.stop(); };
  }, [nodes, links]);

  return <svg ref={ref} style={{ width: "100%", height: "100%" }} />;
}
