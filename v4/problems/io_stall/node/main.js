// io_stall (Node.js): append 4 KB and fsync every 5 ms with the synchronous calls (so the event
// loop thread itself blocks), reporting how long each write+fsync took. See ../problem.sh.
const fs = require('fs');
const fd = fs.openSync('/mnt/v4io/node.dat', 'a');
const buf = Buffer.alloc(4096, 'x');
const now = () => Number(process.hrtime.bigint()) / 1e6;    // ms
let ops = 0, sum = 0, mx = 0, next = now(), report = next + 1000;
function op() {
  const t0 = now();
  fs.writeSync(fd, buf);
  fs.fsyncSync(fd);
  const d = now() - t0;
  ops++; sum += d; mx = Math.max(mx, d);
  if (now() >= report) {
    console.log(`stats ops=${ops} op_avg_ms=${(ops ? sum / ops : 0).toFixed(3)} op_max_ms=${mx.toFixed(3)}`);
    ops = sum = mx = 0;
    report += 1000;
    if (now() > report) report = now() + 1000;
  }
  next += 5;
  if (now() > next) next = now();
  setTimeout(op, Math.max(0, next - now()));
}
op();
