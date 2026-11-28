// deadlock (Node.js, worker_threads with a futex-style mutex on shared memory). See ../problem.sh.
// Node has one JavaScript thread per isolate, so the "threads" are worker_threads; the locks are
// built from Atomics.compareExchange and Atomics.wait (a futex wait in the kernel).
const { Worker, isMainThread, workerData } = require('worker_threads');
const fs = require('fs');

// shared Int32Array: [0] lock A, [1] lock B, [2] jobs done, [3] spare (used for sleeping)
function lock(m, i) {
  while (Atomics.compareExchange(m, i, 0, 1) !== 0) Atomics.wait(m, i, 1);
}
function unlock(m, i) {
  Atomics.store(m, i, 0);
  Atomics.notify(m, i, 1);
}
function sleepMs(m, ms) { Atomics.wait(m, 3, 0, ms); }
function spinUs(us) {
  const t0 = process.hrtime.bigint();
  while (process.hrtime.bigint() - t0 < BigInt(us) * 1000n) { }
}

if (isMainThread) {
  const sab = new SharedArrayBuffer(16);
  const m = new Int32Array(sab);
  const flag = process.env.V4_FLAG || '/dev/shm/v4_fault';
  for (let i = 0; i < 8; i++) new Worker(__filename, { workerData: { sab, role: 'worker' } });
  let started = 0;
  setInterval(() => {
    if (!started && fs.existsSync(flag)) {
      new Worker(__filename, { workerData: { sab, role: 'wrong_order' } });
      started = 1;
    }
    console.log(`stats done=${Atomics.exchange(m, 2, 0)} wrong_order=${started}`);
  }, 1000);
} else {
  const m = new Int32Array(workerData.sab);
  if (workerData.role === 'worker') {
    for (;;) {
      lock(m, 0); lock(m, 1);
      spinUs(50);
      unlock(m, 1); unlock(m, 0);
      Atomics.add(m, 2, 1);
      sleepMs(m, 1);
    }
  } else {                       // the fault: B first, then A
    for (;;) {
      lock(m, 1); sleepMs(m, 1); lock(m, 0);
      spinUs(50);
      unlock(m, 0); unlock(m, 1);
      sleepMs(m, 1);
    }
  }
}
