/*
 * Force layout for the Citation Galaxy. process.py runs this script with Node.
 * Input on stdin: JSON with n, x, y, src, dst, rTarget, ticks.
 * Output on stdout: JSON with x and y arrays.
 * Forces: many-body repulsion, link springs, and a radial spring that holds
 * each star at the radius of its decision year.
 * The script loads d3 7.9.0 from the path in argv[2]. fetch.py downloads it.
 */
const d3 = require(process.argv[2]);
let raw = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (c) => { raw += c; });
process.stdin.on("end", () => {
  const inp = JSON.parse(raw);
  const nodes = [];
  for (let i = 0; i < inp.n; i++) nodes.push({ index: i, x: inp.x[i], y: inp.y[i], r: inp.rTarget[i] });
  const links = [];
  for (let i = 0; i < inp.src.length; i++) links.push({ source: inp.src[i], target: inp.dst[i] });
  const sim = d3.forceSimulation(nodes)
    .force("charge", d3.forceManyBody().strength(inp.charge).theta(0.9).distanceMin(2))
    .force("link", d3.forceLink(links).distance(inp.linkDistance))
    .force("radial", d3.forceRadial((d) => d.r, 0, 0).strength(inp.radialStrength))
    .alphaDecay(1 - Math.pow(0.001, 1 / inp.ticks))
    .stop();
  for (let t = 0; t < inp.ticks; t++) {
    sim.tick();
    if (t % 50 === 0) process.stderr.write(`  tick ${t} alpha ${sim.alpha().toFixed(3)}\n`);
  }
  process.stdout.write(JSON.stringify({ x: nodes.map((d) => d.x), y: nodes.map((d) => d.y) }));
});
