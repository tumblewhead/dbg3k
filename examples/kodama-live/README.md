# Continuous Kodama lesson on AN505

This application owns a permanent C superloop and a real QEMU SysTick interrupt.
It reuses Kodama's existing C-main init/worker/producer coroutine tasks, leaving
that checkout and its finite regression example unchanged. The first run starts
immediately, then one new trigger arrives per **emulated second**. A run starts
only when all previous tasks have finished and their frames have been reclaimed.
Main never returns; startup also parks if a future main accidentally returns.

## Start the same ELF in QEMU and dbg3k

From the dbg3k repository, terminal 1:

```sh
make -C examples/kodama-live KODAMA_DIR=/home/easy/proj/kodama debug
```

Terminal 2, also from dbg3k:

```sh
.venv/bin/python -m dbg3k "$PWD/examples/kodama-live/build/live.elf" \
  --remote localhost:1234 --kodama \
  --kodama-header /home/easy/proj/kodama/examples/c-main/task_config.hpp \
  --history-dir ./kodama-live-history
```

Replace the Kodama checkout path in both commands if needed. Both commands use
the new **live.elf**, not the old finite demo. The Makefile recompiles the complete
small example every time with matching configuration. `GDB_PORT=1235` selects a
different port; pass that port to dbg3k too. `make ... run` starts without GDB.
The build writes only its OUT directory, never the Kodama checkout.

In dbg3k use F2, `tbreak main`, then F2, `continue`. Source stepping and the Kodama
view work as before. `break demo_cycle_complete` stops after each run's tasks are
gone, before the completion counter increments. Continue to inspect later runs;
generation tokens distinguish reused slots. Ctrl-C in QEMU's own terminal stops
the process. Quitting a task is not the same as stopping this superloop.

## Clock and overload policy

The AN505 default 20 MHz system clock drives SysTick at100 Hz (reload199999).
Every interrupt delivers exactly one logical tick with
`kodama_time_advance(1,1)`; every100 interrupts sets a pending run flag. Thus the
existing `sleep(2)` waits two10 ms logical ticks, rather than the old example's
instantaneous idle-driven increments. The original example messages retain
their tick units. ISR-origin expiry can promote a job; explicit completion ends
that promotion. No coroutine executes inside the timer handler.

There is at most one pending run, not an unbounded queue or overlapping task set.
If a run is still active, the next trigger stays pending; further triggers
coalesce and increment `demo_coalesced_triggers`. A delayed run starts as soon as
the previous one finishes; periodic trigger phase is not reset by completion.
The application lowers INIT_READY before spawning each new Init so children
actually repeat their initialization wait. New frames receive new generations.

Inspect `demo_ticks`, `demo_second_triggers`, `demo_cycle_pending`,
`demo_cycles_started`, `demo_cycles_completed`, `demo_coalesced_triggers` and
`demo_failed` as globals. Each completion verifies allocation/free balance before
printing its success message. An application error parks visibly in an infinite
error loop instead of exiting QEMU. Existing task assertions can still call the
original example's error exit: continuous normal operation is not fault recovery.

Idle main uses WFE. SysTick issues SEV so a trigger between the idle check and WFE
is not lost. WFE use is not measured power or proof of sleep residency. Debugger
halts, breakpoint sampling, emulator load and host scheduling can stretch wall
time. Debug stops may coalesce hardware timer notifications; this teaching port
does not reconstruct elapsed wall time or lost timer periods.

This is an SRAM-only image at0x38000000 using the existing Kodama linker layout.
AN505 emulates M33 while GCC targets M23 instructions; physical M23 and real-time
latency/stack bounds remain unqualified. Newlib console/runtime and the demo's
heap/stack reservations are application costs, not minimal Kodama footprint.

dbg3k's existing observation limits still apply:4096 samples per capture and512
visible samples. Timer entry probes consume that budget too. At the limit QEMU
keeps running; pause/restart capture at a halted stop to begin a fresh segment.

## Reproduce the real-target check

```sh
DBG3K_QEMU_TEST=1 DBG3K_KODAMA_SOURCE=/home/easy/proj/kodama \
  DBG3K_LIVE_RECEIPT=/tmp/dbg3k-live-receipt PYTHONPATH=src \
  .venv/bin/python -m unittest discover -s tests -p test_qemu_live_demo.py -v
```

The test builds from that actual checkout in a temporary output directory,
attaches GDB, verifies source at main and stops at the third completion. It reads
clock/trigger counters and allocator state without inferior function calls,
then detaches and proves a fourth run completes while QEMU stays alive. Receipt
logs are local and opt-in. No physical hardware or interactive terminal check
is implied by the headless debugger test.
