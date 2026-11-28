// lock_contention (Node.js, worker_threads with a futex-style mutex). See ../problem.sh.
const { Worker, isMainThread, workerData } = require('worker_threads');
const fs = require('fs');

// shared Int32Array: [0] lock, [1] fault, [2] done, [3] sleep word; BigInt64Array: [0] wait ns, [1] max wait ns
function lock(m, i) { while (Atomics.compareExchange(m, i, 0, 1) !== 0) Atomics.wait(m, i, 1); }
function unlock(m, i) { Atomics.store(m, i, 0); Atomics.notify(m, i, 1); }
function spinUs(us) {
  const t0 = process.hrtime.bigint();
  while (process.hrtime.bigint() - t0 < BigInt(us) * 1000n) { }
}

if (isMainThread) {
  const sab = new SharedArrayBuffer(16), sab64 = new SharedArrayBuffer(16);
  const m = new Int32Array(sab), w = new BigInt64Array(sab64);
  const flag = process.env.V4_FLAG || '/dev/shm/v4_fault';
  for (let i = 0; i < 16; i++) new Worker(__filename, { workerData: { sab, sab64 } });
  let tick = 0;
  setInterval(() => {
    Atomics.store(m, 1, fs.existsSync(flag) ? 1 : 0);
    if (++tick % 10) return;
    const n = Atomics.exchange(m, 2, 0), ws = Number(Atomics.exchange(w, 0, 0n)), mx = Number(Atomics.exchange(w, 1, 0n));
    console.log(`stats done=${n} wait_avg_ms=${(n ? ws / 1e6 / n : 0).toFixed(3)} wait_max_ms=${(mx / 1e6).toFixed(3)} fault=${Atomics.load(m, 1)}`);
  }, 100);
} else {
  const m = new Int32Array(workerData.sab), w = new BigInt64Array(workerData.sab64);
  for (;;) {
    const t0 = process.hrtime.bigint();
    lock(m, 0);
    const wt = process.hrtime.bigint() - t0;
    spinUs(Atomics.load(m, 1) ? 2000 : 20);
    unlock(m, 0);
    Atomics.add(m, 2, 1);
    Atomics.add(w, 0, wt);
    for (let x = Atomics.load(w, 1); wt > x && Atomics.compareExchange(w, 1, x, wt) !== x; x = Atomics.load(w, 1)) { }
    Atomics.wait(m, 3, 0, 1);
  }
}
