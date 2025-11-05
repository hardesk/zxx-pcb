
#TOOLCHAIN=/opt/homebrew/Cellar/riscv-gnu-toolchain/main/bin/riscv64-unknown-elf
TOOLCHAIN=/opt/riscv32i/bin/riscv32-unknown-elf
CCOPT=-nostdlib -Os -Wno-builtin-declaration-mismatch -march=rv32imc_zicsr_zifencei 
#CCOPT=-nostdlib -Os -Wno-builtin-declaration-mismatch -march=rv32i
#FWDIR=../caravel_board/firmware/mpw2-5
FWDIR=../../../caravel_board/firmware/chipignite

.PHONY: clean

z80fw: z80_boot.c
	$(TOOLCHAIN)-gcc $(CCOPT) -I$(FWDIR)/ -T$(FWDIR)/sections.lds $(FWDIR)/crt0_vex.S $(FWDIR)/isr.c -o $@.elf $^
	$(TOOLCHAIN)-objcopy -O binary $@.elf $@

clean:
	rm z80fw z80fw.elf
