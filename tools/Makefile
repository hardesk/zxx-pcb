
#TOOLCHAIN=/opt/homebrew/Cellar/riscv-gnu-toolchain/main/bin/riscv64-unknown-elf
TOOLCHAIN=/opt/riscv32i/bin/riscv32-unknown-elf
#CCOPT=-march=rv32imc_zicsr_zifencei 
CCOPT=-mabi=ilp32 -march=rv32i_zicsr -ffreestanding -nostdlib -D__vexriscv__ -O0 -Wno-builtin-declaration-mismatch 
LOPT=-Wl,-Bstatic,-T,sections.lds,--strip-debug
#CCOPT=-nostdlib -Os -Wno-builtin-declaration-mismatch -march=rv32i
#FWDIR=../caravel_board/firmware/mpw2-5
FWDIR=../../caravel_board/firmware/chipignite

.PHONY: clean all

all: derived/z80fw.hex derived/z80fw.bin

derived/z80fw.hex: derived/z80fw.elf
	$(TOOLCHAIN)-objcopy -O verilog $< $@
	sed -ie 's/@1000/@0000/g' $@

derived/z80fw.bin: derived/z80fw.elf
	$(TOOLCHAIN)-objcopy -O binary $< $@

derived/z80fw.elf: z80_boot.c crt0_vex.S $(FWDIR)/isr.c $(FWDIR)/stub.c | dirs
	$(TOOLCHAIN)-gcc $(CCOPT) -I$(FWDIR)/ $(LOPT) -o $@ $^

clean:
	rm -f derived/*

dirs: derived

derived:
	mkdir -p derived
