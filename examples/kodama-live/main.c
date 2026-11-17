/* Continuous teaching application; Kodama owns neither this clock nor main. */
#include <stdint.h>
#include <stdio.h>
#include "kodama.h"
#include "app.h"

extern int demo_start_cycle(void);
volatile unsigned demo_ticks;
volatile unsigned demo_second_triggers;
volatile unsigned demo_coalesced_triggers;
volatile unsigned demo_cycle_pending = 1;
volatile unsigned demo_cycles_started;
volatile unsigned demo_cycles_completed;
volatile unsigned demo_failed;

void SysTick_Handler(void) {
    static unsigned phase;
    ++demo_ticks;
    if (!kodama_time_advance(1, 1)) demo_failed = 1;
    if (++phase == KODAMA_TICKS_PER_SECOND) {
        phase = 0;
        ++demo_second_triggers;
        if (demo_cycle_pending) ++demo_coalesced_triggers;
        demo_cycle_pending = 1;
    }
    /* Sticky event closes the check-before-WFE race in the main loop. */
    __asm__ volatile("sev" ::: "memory");
}

static unsigned take_trigger(void) {
    unsigned mask, pending;
    __asm__ volatile("mrs %0, primask\ncpsid i" : "=r"(mask) :: "memory");
    pending = demo_cycle_pending;
    demo_cycle_pending = 0;
    __asm__ volatile("msr primask, %0" :: "r"(mask) : "memory");
    return pending;
}

/* Named lesson milestone: safe to break here after every complete run. */
__attribute__((noinline)) void demo_cycle_complete(void) {
    ++demo_cycles_completed;
    printf("LIVE cycle %u complete: all frames reclaimed; tick %u\n",
           demo_cycles_completed, demo_ticks);
}

int main(void) {
    volatile uint32_t *systick = (volatile uint32_t *)0xe000e010u;
    unsigned active = 0;
    puts("Kodama live superloop: one trigger per emulated second; Ctrl-C in QEMU terminal to stop.");
    /* AN505 default system clock is 20 MHz. 100 IRQs/logical ticks per second. */
    systick[0] = 0;
    systick[1] = 20000000u / KODAMA_TICKS_PER_SECOND - 1u;
    systick[2] = 0;
    systick[0] = 7;
    for (;;) {
        if (demo_failed) {
            systick[0] = 0;
            puts("LIVE ERROR: inspect demo_failed; target remains in application error loop");
            for (;;) __asm__ volatile("wfe");
        }
        if (active && !app_live_tasks()) {
            if (!app_frames_reclaimed()) { demo_failed = 1; continue; }
            active = 0;
            demo_cycle_complete();
        }
        if (!active && take_trigger()) {
            if (!demo_start_cycle()) { demo_failed = 1; continue; }
            active = 1;
            ++demo_cycles_started;
            printf("LIVE cycle %u started: tick %u\n", demo_cycles_started, demo_ticks);
        }
        if (!kodama_run_one()) __asm__ volatile("wfe" ::: "memory");
    }
}
