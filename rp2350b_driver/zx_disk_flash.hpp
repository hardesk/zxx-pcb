#pragma once
#include <hardware/flash.h>
#include <hardware/regs/addressmap.h>
#include "zx_disk.hpp"

// TRD slots in the last 4 MiB of the 16 MiB flash, 1 MiB per drive. Reads use
// the uncached, untranslated XIP alias, so disk traffic neither evicts ROM
// lines from the XIP cache nor depends on address translation.
class ZxFlashDiskBackend final : public ZxDiskBackend {
public:
    static constexpr uint32_t slot_size = 1024 * 1024;
    static constexpr uint32_t region_offset = PICO_FLASH_SIZE_BYTES - ZxDiskStore::drives * slot_size;
    static_assert(ZxDiskStore::slot_blocks * block_size <= slot_size);
    static_assert(region_offset >= 2 * 1024 * 1024, "Keep at least 2 MiB for firmware");

    const uint8_t* block(unsigned drive, unsigned index) const override {
        return reinterpret_cast<const uint8_t*>(XIP_NOCACHE_NOALLOC_NOTRANSLATE_BASE +
                                                offset(drive, index));
    }
    // Erase and program one 4 KiB sector with core1 locked out and IRQs off.
    // Takes ~30-100 ms, during which the Z80 waits on its next request.
    bool program(unsigned drive, unsigned index, const uint8_t* data) override;

    static uint32_t offset(unsigned drive, unsigned index) {
        return region_offset + drive * slot_size + index * block_size;
    }
};
