KODAMA_DIR ?= ../../../kodama
KODAMA := $(abspath $(KODAMA_DIR))
OUT ?= $(CURDIR)/build
OUT := $(abspath $(OUT))
CROSS ?= arm-none-eabi-
QEMU ?= qemu-system-arm
GDB_PORT ?= 1234
FLAGS = -mcpu=cortex-m23 -mthumb -O0 -g3 -gdwarf-4 -ffunction-sections -fdata-sections -fno-omit-frame-pointer -Wall -Wextra -Werror
FLAGS += -I$(KODAMA)/include -I$(KODAMA)/examples/c-main -DKODAMA_ENABLE_PRIORITY_JOBS=1 -DKODAMA_ENABLE_EVENTS=1 -DKODAMA_ENABLE_TIMERS=1 -DKODAMA_TICKS_PER_SECOND=100 -DKODAMA_FRAME_BYTES=512 -DKODAMA_DIAGNOSTICS=1
C_SOURCES = main.c startup.c $(KODAMA)/src/kodama.c
CPP_SOURCES = cycle.cpp $(KODAMA)/src/coroutine.cpp $(addprefix $(KODAMA)/examples/c-main/,app.cpp init.cpp task1.cpp task2.cpp)

.PHONY: all run debug
# Recompile the small lesson on every invocation: no stale profile/header objects.
all:
	test -f "$(KODAMA)/include/kodama.h"
	mkdir -p "$(OUT)"
	@set -e; for source in $(C_SOURCES); do \
	  $(CROSS)gcc $(FLAGS) -std=c11 -c "$$source" -o "$(OUT)/$$(basename "$$source" .c).o"; done
	@set -e; for source in $(CPP_SOURCES); do \
	  $(CROSS)g++ $(FLAGS) -std=c++20 -fno-exceptions -fno-rtti -fno-threadsafe-statics -c "$$source" -o "$(OUT)/$$(basename "$$source" .cpp).o"; done
	$(CROSS)gcc -mcpu=cortex-m23 -mthumb -g3 -nostartfiles --specs=nano.specs --specs=rdimon.specs -Wl,--build-id=none -Wl,-T,$(KODAMA)/examples/c-main/arm/sram.ld -Wl,--gc-sections -Wl,-Map,$(OUT)/live.map $(addprefix $(OUT)/,startup.o main.o kodama.o cycle.o coroutine.o app.o init.o task1.o task2.o) -o "$(OUT)/live.elf"
	$(CROSS)size "$(OUT)/live.elf"

run: all
	$(QEMU) -M mps2-an505 -display none -serial none -monitor none -semihosting-config enable=on,target=native -device loader,file=$(OUT)/live.elf,cpu-num=0

debug: all
	$(QEMU) -M mps2-an505 -display none -serial none -monitor none -semihosting-config enable=on,target=native -device loader,file=$(OUT)/live.elf,cpu-num=0 -S -gdb tcp:127.0.0.1:$(GDB_PORT)
