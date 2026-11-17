/* AN505 Secure SRAM teaching runtime, with a real SysTick vector. */
#include <stdint.h>
#include <stdlib.h>
extern uint32_t __stack_top, __data_start, __data_end, __data_load;
extern uint32_t __bss_start, __bss_end;
extern int main(void);
extern void SysTick_Handler(void);
extern void initialise_monitor_handles(void);
extern void __libc_init_array(void);
void _init(void) {}
void _fini(void) {}
void Default_Handler(void) { for (;;) __asm__ volatile("wfe"); }
void Boot_Handler(void) {
    *(volatile uint32_t *)0xe000ed08u = 0x38000000u;
    __asm__ volatile("dsb\nisb" ::: "memory");
    uint32_t *source = &__data_load;
    for (uint32_t *p = &__data_start; p < &__data_end;) *p++ = *source++;
    for (uint32_t *p = &__bss_start; p < &__bss_end;) *p++ = 0;
    initialise_monitor_handles();
    __libc_init_array();
    (void)main();
    /* Even an accidental future return from main must not end the session. */
    for (;;) __asm__ volatile("wfe");
}
__attribute__((naked, noreturn)) void Reset_Handler(void) {
    __asm__ volatile("ldr r0, =__stack_top\nmsr msp, r0\nb Boot_Handler");
}
__attribute__((section(".vectors"), used))
const uintptr_t vectors[16] = {
    (uintptr_t)&__stack_top, (uintptr_t)Reset_Handler,
    [2 ... 14] = (uintptr_t)Default_Handler,
    [15] = (uintptr_t)SysTick_Handler
};
