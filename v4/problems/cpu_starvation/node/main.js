// cpu_starvation (Node.js): a 10 ms periodic task with 1 ms of work, reporting its wake-up
// lateness. The task runs on the event loop (setTimeout). See ../problem.sh.
const now = () => Number(process.hrtime.bigint()) / 1e6;     // ms
let late = [];
let next = now(), report = next + 1000;
function tick() {
  const t = now();
  late.push(t - next);
  while (now() - t < 1) { }                                   // 1 ms of work
  if (t >= report) {
    const s = late.slice().sort((a, b) => a - b), n = s.length;
    console.log(`stats ticks=${n} late_p50_ms=${s[n >> 1].toFixed(3)} late_p99_ms=${s[Math.floor(n * 99 / 100)].toFixed(3)} late_max_ms=${s[n - 1].toFixed(3)}`);
    late = [];
    report += 1000;
  }
  next += 10;
  if (now() > next + 10) next = now();
  setTimeout(tick, Math.max(0, next - now()));
}
next += 10;
setTimeout(tick, 10);
