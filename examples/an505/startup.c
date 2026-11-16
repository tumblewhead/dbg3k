#include <stdint.h>
extern uint32_t _stack_top, _sidata, _sdata, _edata, _sbss, _ebss;
extern int main(void);
void Reset_Handler(void);
void Default_Handler(void);

__attribute__((used, section(".vectors")))
const uintptr_t vectors[48] = {
    [0] = (uintptr_t)&_stack_top,
    [1] = (uintptr_t)Reset_Handler,
    [2 ... 47] = (uintptr_t)Default_Handler,
};

void Reset_Handler(void)
{
    uint32_t *src = &_sidata;
    for (uint32_t *p = &_sdata; p < &_edata;) *p++ = *src++;
    for (uint32_t *p = &_sbss; p < &_ebss;) *p++ = 0;
    (void)main();
    for (;;) __asm volatile("wfi");
}

void Default_Handler(void)
{
    for (;;) __asm volatile("wfi");
}
