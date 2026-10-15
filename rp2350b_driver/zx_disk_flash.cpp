#include "zx_disk_flash.hpp"

#include <hardware/structs/qmi.h>
#include <pico/flash.h>

namespace {

struct ProgramBlock {
    uint32_t offset;
    const uint8_t* data; // SRAM: flash is not readable during the operation.
};

// Runs from SRAM. The SDK re-enters XIP through the boot2 copy, which
// restores the boot-time QMI timing; main() slowed SCK for the raised
// clk_sys, so put that timing back before anything executes from flash.
void __no_inline_not_in_flash_func(erase_and_program)(void* parameter)
{
    const auto* op = static_cast<const ProgramBlock*>(parameter);
    const uint32_t timing = qmi_hw->m[0].timing;
    flash_range_erase(op->offset, FLASH_SECTOR_SIZE);
    flash_range_program(op->offset, op->data, FLASH_SECTOR_SIZE);
    qmi_hw->m[0].timing = timing;
    (void)qmi_hw->m[0].timing;
}

} // namespace

static_assert(FLASH_SECTOR_SIZE == ZxDiskBackend::block_size);

bool ZxFlashDiskBackend::program(unsigned drive, unsigned index, const uint8_t* data)
{
    if (drive >= ZxDiskStore::drives || index >= ZxDiskStore::slot_blocks) return false;
    ProgramBlock op{offset(drive, index), data};
    return flash_safe_execute(erase_and_program, &op, 1000) == PICO_OK;
}
