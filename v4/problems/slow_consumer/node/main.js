// slow_consumer (Node.js, one event loop: the producer is a timer, the consumer an async loop).
// See ../problem.sh.
const fs = require('fs');
const flag = process.env.V4_FLAG || '/dev/shm/v4_fault';
const now = () => Number(process.hrtime.bigint()) / 1e6;    // ms
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const q = [];
let fault = false, consumed = 0, ageMax = 0;

let next = now();
function produce() {                                         // one 8 KB item every 2 ms
  q.push({ t: now(), data: Buffer.alloc(8192, 7) });
  next += 2;
  setTimeout(produce, Math.max(0, next - now()));
}
async function consume() {
  for (;;) {
    if (!q.length) { await sleep(1); continue; }
    const it = q.shift();
    ageMax = Math.max(ageMax, now() - it.t);
    if (fault) await sleep(3);
    else { const t0 = now(); while (now() - t0 < 1) { } await sleep(0); }
    consumed++;
  }
}
let tick = 0;
setInterval(() => {
  fault = fs.existsSync(flag);
  if (++tick % 10) return;
  console.log(`stats consumed=${consumed} queue_len=${q.length} item_age_ms=${ageMax.toFixed(3)} fault=${fault ? 1 : 0}`);
  consumed = 0; ageMax = 0;
}, 100);
produce();
consume();
