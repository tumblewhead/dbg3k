CC = arm-none-eabi-gcc
CFLAGS = -mcpu=cortex-m33 -mthumb -O0 -g3 -ffreestanding -fno-builtin -ffunction-sections -fdata-sections
LDFLAGS = -nostdlib -T linker.ld -Wl,--gc-sections -Wl,-Map=firmware.map
all: firmware.elf
firmware.elf: startup.c main.c linker.ld
	$(CC) $(CFLAGS) $(LDFLAGS) startup.c main.c -o $@
run: firmware.elf
	qemu-system-arm -M mps2-an505 -nographic -monitor none -semihosting-config enable=on,target=native -kernel firmware.elf
debug: firmware.elf
	qemu-system-arm -M mps2-an505 -nographic -monitor none -semihosting-config enable=on,target=native -kernel firmware.elf -S -gdb tcp::1234
clean:
	rm -f firmware.elf firmware.map
.PHONY: all run debug clean
