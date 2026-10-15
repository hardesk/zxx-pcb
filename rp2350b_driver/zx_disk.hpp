#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>
#include "zx_tape.hpp" // tape_crc_update

// TR-DOS disks: up to four TRD images in fixed slots of a block device, and
// a Beta 128 interface (WD1793 + system register) that TR-DOS drives.
//
// Slot layout, 4 KiB blocks: block 0 is the header, block n+1 holds image
// bytes n*4096..n*4096+4095. Images are 256-byte sectors in TRD order
// (cylinder, side, sector 1..16); bytes past the stored size read as zero,
// so the host can upload an image without its empty tail.

// Erase/program granularity of the backing store (flash sector).
class ZxDiskBackend {
public:
    static constexpr unsigned block_size = 4096;
    virtual ~ZxDiskBackend() = default;
    // Readable view of a block: XIP flash on the RP, memory in tests.
    virtual const uint8_t* block(unsigned drive, unsigned index) const = 0;
    // Replace a block. Holds the CPU (it is in WAIT, or between requests).
    virtual bool program(unsigned drive, unsigned index, const uint8_t* data) = 0;
};

class ZxDiskStore {
public:
    static constexpr unsigned drives = 4, name_max = 24;
    static constexpr uint32_t max_image = 80 * 2 * 16 * 256; // 640 KiB, 80 cylinders, 2 sides
    static constexpr unsigned block_size = ZxDiskBackend::block_size;
    static constexpr unsigned slot_blocks = 1 + max_image / block_size;

    struct Info {
        bool present = false, write_protect = false;
        uint32_t size = 0, crc = 0;
        char name[name_max + 1] = {};
    };

    explicit ZxDiskStore(ZxDiskBackend& backend) : backend_(backend) {}

    // Read headers left in the slots by earlier uploads (persistent mounts).
    void load() {
        for (unsigned d = 0; d < drives; ++d) {
            info_[d] = Info{};
            Header h; memcpy(&h, backend_.block(d, 0), sizeof h);
            if (h.magic != magic || h.check != header_check(h) || h.size > max_image || h.size % 256)
                continue;
            info_[d].present = true;
            info_[d].write_protect = h.flags & 1;
            info_[d].size = h.size;
            info_[d].crc = h.crc;
            memcpy(info_[d].name, h.name, name_max);
            info_[d].name[name_max] = 0;
        }
        ++generation_;
    }

    const Info& info(unsigned drive) const { return info_[drive]; }
    bool present(unsigned drive) const { return drive < drives && info_[drive].present; }
    // Bumped on every mount change; lets the controller drop cached geometry.
    unsigned generation() const { return generation_; }

    // One 256-byte sector at an image offset (a multiple of 256).
    void read_sector(unsigned drive, uint32_t offset, uint8_t* out) const {
        const unsigned index = offset / block_size, within = offset % block_size;
        if (dirty_ && cache_drive_ == drive && cache_index_ == index) {
            memcpy(out, cache_ + within, 256);
        } else if (offset >= info_[drive].size) {
            memset(out, 0, 256);
        } else {
            memcpy(out, backend_.block(drive, index + 1) + within, 256);
        }
    }
    uint8_t read_byte(unsigned drive, uint32_t offset) const {
        uint8_t sector[256];
        read_sector(drive, offset & ~255u, sector);
        return sector[offset & 255];
    }

    // Buffered: a block is programmed once when the next write leaves it,
    // on flush(), or on any mount change.
    bool write_sector(unsigned drive, uint32_t offset, const uint8_t* data) {
        if (!present(drive) || info_[drive].write_protect || offset + 256 > max_image) return false;
        const unsigned index = offset / block_size;
        if (!dirty_ || cache_drive_ != drive || cache_index_ != index) {
            if (!flush()) return false;
            load_block(drive, index, cache_);
            cache_drive_ = drive; cache_index_ = index;
        }
        memcpy(cache_ + offset % block_size, data, 256);
        dirty_ = true;
        return true;
    }
    bool dirty() const { return dirty_; }
    bool flush() {
        if (!dirty_) return true;
        const unsigned drive = cache_drive_;
        dirty_ = false;
        if (!backend_.program(drive, cache_index_ + 1, cache_)) return false;
        const uint32_t end = (cache_index_ + 1) * block_size;
        if (end > info_[drive].size) {
            // The block was zero-filled past the old end; extend the image.
            info_[drive].size = end < max_image ? end : max_image;
            info_[drive].crc = 0; // No longer the uploaded file.
            return write_header(drive);
        }
        return true;
    }

    bool eject(unsigned drive) {
        if (drive >= drives || uploading()) return false;
        if (!flush()) return false;
        const bool was = info_[drive].present;
        info_[drive] = Info{};
        ++generation_;
        return !was || erase_header(drive);
    }

    // Host upload into one slot. begin() ejects the drive; the image is
    // mounted only by a commit() whose size and CRC match.
    bool begin(unsigned drive, uint32_t size, uint32_t crc, bool write_protect,
               const char* name, unsigned name_length) {
        if (drive >= drives || size == 0 || size > max_image || size % 256) return false;
        abort_upload();
        if (!flush()) return false;
        if (info_[drive].present && !erase_header(drive)) return false;
        info_[drive] = Info{};
        info_[drive].write_protect = write_protect;
        info_[drive].size = size; info_[drive].crc = crc;
        unsigned n = 0;
        for (unsigned i = 0; i < name_length && n < name_max; ++i) {
            const char c = name[i];
            info_[drive].name[n++] = (c >= 32 && c < 127 && c != '"' && c != '\\') ? c : '_';
        }
        upload_drive_ = int(drive); received_ = 0; running_crc_ = 0xffffffffu;
        ++generation_;
        return true;
    }
    bool chunk(uint32_t offset, const uint8_t* data, uint32_t size) {
        if (!uploading()) return false;
        const Info& target = info_[upload_drive_];
        if (offset != received_ || size == 0 || size > target.size - received_) return false;
        running_crc_ = tape_crc_update(running_crc_, data, size);
        while (size) {
            const unsigned within = received_ % block_size;
            const unsigned n = size < block_size - within ? size : block_size - within;
            memcpy(upload_ + within, data, n);
            data += n; size -= n; received_ += n;
            if (received_ % block_size == 0 || received_ == target.size) {
                const unsigned index = (received_ - 1) / block_size;
                const unsigned used = received_ - index * block_size;
                memset(upload_ + used, 0, block_size - used);
                // Remounting the same image rewrites nothing.
                if (memcmp(backend_.block(upload_drive_, index + 1), upload_, block_size) != 0 &&
                    !backend_.program(upload_drive_, index + 1, upload_)) {
                    abort_upload();
                    return false;
                }
                ++programmed_blocks_;
            }
        }
        return true;
    }
    bool commit() {
        if (!uploading()) return false;
        const unsigned drive = upload_drive_;
        if (received_ != info_[drive].size || (running_crc_ ^ 0xffffffffu) != info_[drive].crc) return false;
        upload_drive_ = -1;
        if (!write_header(drive)) { info_[drive] = Info{}; return false; }
        info_[drive].present = true;
        ++generation_;
        return true;
    }
    void abort_upload() {
        if (uploading()) info_[upload_drive_] = Info{};
        upload_drive_ = -1; received_ = 0;
    }
    bool uploading() const { return upload_drive_ >= 0; }
    int upload_drive() const { return upload_drive_; }
    uint32_t received() const { return received_; }
    unsigned programmed_blocks() const { return programmed_blocks_; }

private:
    static constexpr uint32_t magic = 0x314b445a; // "ZDK1"
    struct Header {
        uint32_t magic, size, crc, flags;
        char name[name_max];
        uint32_t check;
    };
    static uint32_t header_check(const Header& h) {
        return tape_crc(reinterpret_cast<const uint8_t*>(&h), offsetof(Header, check));
    }

    void load_block(unsigned drive, unsigned index, uint8_t* out) const {
        const uint32_t start = index * block_size, size = info_[drive].size;
        if (start >= size) { memset(out, 0, block_size); return; }
        const uint32_t valid = size - start < block_size ? size - start : block_size;
        memcpy(out, backend_.block(drive, index + 1), valid);
        memset(out + valid, 0, block_size - valid);
    }
    bool write_header(unsigned drive) {
        Header h{};
        h.magic = magic; h.size = info_[drive].size; h.crc = info_[drive].crc;
        h.flags = info_[drive].write_protect ? 1 : 0;
        memcpy(h.name, info_[drive].name, name_max);
        h.check = header_check(h);
        memset(upload_, 0xff, block_size);
        memcpy(upload_, &h, sizeof h);
        return backend_.program(drive, 0, upload_);
    }
    bool erase_header(unsigned drive) {
        memset(upload_, 0xff, block_size);
        return backend_.program(drive, 0, upload_);
    }

    ZxDiskBackend& backend_;
    Info info_[drives];
    unsigned generation_ = 0, programmed_blocks_ = 0;
    // Write-back cache for one image block.
    uint8_t cache_[block_size];
    unsigned cache_drive_ = 0, cache_index_ = 0;
    bool dirty_ = false;
    // Upload staging; also scratch for header writes.
    uint8_t upload_[block_size];
    int upload_drive_ = -1;
    uint32_t received_ = 0, running_crc_ = 0;
};

// Beta 128 disk interface as TR-DOS sees it, decoded only while the TR-DOS
// ROM is paged in:
//   1F status/command  3F track  5F sector  7F data   (WD1793, A7=0)
//   FF system register (A7=1): write bits 1:0 drive, 2 /reset, 3 HLT,
//      4 side (0 = upper head), 6 density; read bit 7 INTRQ, bit 6 DRQ
// Commands complete immediately: the CPU sees DRQ as soon as it polls, and
// rotation shows only as index pulses (300 rpm) in the Type I status, and
// in Write Track, which ends with Lost Data if no byte arrives before the
// next index pulse (TR-DOS 5.03 issues a stray FCh this way on drive init).
class ZxBetaDisk {
public:
    explicit ZxBetaDisk(ZxDiskStore& store) : store_(store) {}

    static bool decodes(uint16_t port) { return (port & 0x1f) == 0x1f; }

    void reset() {
        op_ = Op::None; busy_ = drq_ = intrq_ = false;
        status_ = 0; type1_ = true;
        track_ = 0; sector_ = 1; data_ = 0; system_ = 0x3c; direction_ = 1;
    }

    uint8_t read(uint16_t port, uint32_t now_us) {
        if (op_ == Op::WriteTrack && position_ == 0 && revolution(now_us) != command_revolution_) {
            status_ = sLost; finish();
        }
        if (port & 0x80) return uint8_t((intrq_ ? 0x80 : 0) | (drq_ ? 0x40 : 0) | 0x3f);
        switch ((port >> 5) & 3) {
        case 0: intrq_ = false; return status(now_us);
        case 1: return track_;
        case 2: return sector_;
        default: return read_data();
        }
    }

    void write(uint16_t port, uint8_t value, uint32_t now_us) {
        if (port & 0x80) {
            system_ = value;
            if (!(value & 4)) { // /reset: abort, like a power-on WD.
                op_ = Op::None; busy_ = drq_ = intrq_ = false; status_ = 0; type1_ = true; sector_ = 1;
            }
            return;
        }
        switch ((port >> 5) & 3) {
        case 0: command(value, now_us); break;
        case 1: if (!busy_) track_ = value; break;
        case 2: if (!busy_) sector_ = value; break;
        default: write_data(value); break;
        }
    }

    // Diagnostics.
    unsigned drive() const { return system_ & 3; }
    unsigned side() const { return (system_ & 0x10) ? 0 : 1; }
    unsigned cylinder(unsigned drive) const { return cylinder_[drive]; }
    uint32_t sectors_read() const { return sectors_read_; }
    uint32_t sectors_written() const { return sectors_written_; }

private:
    enum class Op : uint8_t { None, Read, Write, ReadAddress, WriteTrack };
    static constexpr uint8_t sBusy = 0x01, sDrq = 0x02, sLost = 0x04, sCrc = 0x08,
        sRnf = 0x10, sSeek = 0x10, sProtect = 0x40, sNotReady = 0x80;
    static constexpr unsigned max_cylinder = 85;

    uint8_t status(uint32_t now_us) const {
        const unsigned d = drive();
        const bool present = store_.present(d);
        uint8_t s = status_ | (busy_ ? sBusy : 0) | (present ? 0 : sNotReady);
        if (type1_) {
            // 200 ms per revolution, ~4 ms index hole.
            if (present && now_us % 200000u < 4000u) s |= 0x02;
            if (cylinder_[d] == 0) s |= 0x04;
            if (system_ & 0x08) s |= 0x20;
            if (present && store_.info(d).write_protect) s |= sProtect;
        } else if (drq_) {
            s |= sDrq;
        }
        return s;
    }

    void finish() { op_ = Op::None; busy_ = drq_ = false; intrq_ = true; }

    static uint32_t revolution(uint32_t now_us) { return now_us / 200000u; }

    void command(uint8_t c, uint32_t now_us) {
        if ((c & 0xf0) == 0xd0) { // Force interrupt; any condition interrupts at once.
            const bool was_busy = busy_;
            op_ = Op::None; busy_ = drq_ = false;
            if (!was_busy) { type1_ = true; status_ = 0; }
            intrq_ = (c & 0x0f) != 0;
            return;
        }
        if (busy_) return;
        intrq_ = drq_ = false; status_ = 0;
        if (!(c & 0x80)) { seek(c); return; }
        type1_ = false;
        const unsigned d = drive();
        if (!store_.present(d)) { status_ = sNotReady; finish(); return; }
        multiple_ = c & 0x10;
        switch (c & 0xf0) {
        case 0x80: case 0x90: start_read(); break;
        case 0xa0: case 0xb0:
            if (store_.info(d).write_protect) { status_ = sProtect; finish(); break; }
            if (!locate(offset_)) { status_ = sRnf; finish(); break; }
            op_ = Op::Write; position_ = 0; busy_ = drq_ = true;
            break;
        case 0xc0: read_address(); break;
        case 0xf0:
            if (store_.info(d).write_protect) { status_ = sProtect; finish(); break; }
            op_ = Op::WriteTrack; position_ = 0; collecting_ = 0; synced_ = id_valid_ = false;
            command_revolution_ = revolution(now_us);
            busy_ = drq_ = true;
            break;
        default: finish(); break; // Read Track: not supported, ends at once.
        }
    }

    void seek(uint8_t c) {
        type1_ = true;
        const unsigned d = drive();
        int cylinder = cylinder_[d];
        switch (c & 0xe0) {
        case 0x00: // Restore (and Seek, bit 4)
            if (c & 0x10) {
                cylinder += int(data_) - int(track_);
                direction_ = data_ >= track_ ? 1 : -1;
                track_ = data_;
            } else {
                cylinder = 0; track_ = 0; direction_ = -1;
            }
            break;
        case 0x40: direction_ = 1; goto step;
        case 0x60: direction_ = -1; goto step;
        default: // 0x20 Step
        step:
            cylinder += direction_;
            if (c & 0x10) track_ = uint8_t(track_ + direction_);
            break;
        }
        cylinder_[d] = uint8_t(cylinder < 0 ? 0 : cylinder > int(max_cylinder) ? max_cylinder : cylinder);
        if ((c & 0x04) && (!store_.present(d) || track_ != cylinder_[d] ||
                           cylinder_[d] >= geometry(d).cylinders))
            status_ |= sSeek;
        finish();
    }

    struct Geometry { unsigned cylinders, sides; };
    // TRD disk type, byte E3 of track 0 sector 9: 16h 80/DS, 17h 40/DS,
    // 18h 80/SS, 19h 40/SS. Anything else is treated as 80/DS.
    Geometry geometry(unsigned d) {
        if (geometry_generation_[d] != store_.generation() + 1) {
            const uint8_t type = store_.read_byte(d, 0x8e3);
            geometry_[d] = {(type == 0x17 || type == 0x19) ? 40u : 80u,
                            (type == 0x18 || type == 0x19) ? 1u : 2u};
            geometry_generation_[d] = store_.generation() + 1;
        }
        return geometry_[d];
    }
    // Sector writes can change disk type (format): re-read it on next use.
    void forget_geometry(unsigned d) { geometry_generation_[d] = 0; }

    bool locate(uint32_t& offset) {
        const unsigned d = drive(), cylinder = cylinder_[d], head = side();
        const Geometry g = geometry(d);
        if (cylinder >= g.cylinders || head >= g.sides || track_ != cylinder ||
            sector_ < 1 || sector_ > 16)
            return false;
        offset = ((cylinder * g.sides + head) * 16u + sector_ - 1u) * 256u;
        return true;
    }

    void start_read() {
        if (!locate(offset_)) { status_ = sRnf; finish(); return; }
        store_.read_sector(drive(), offset_, buffer_);
        ++sectors_read_;
        op_ = Op::Read; position_ = 0; length_ = 256; busy_ = drq_ = true;
    }

    void read_address() {
        const unsigned d = drive();
        const Geometry g = geometry(d);
        if (cylinder_[d] >= g.cylinders || side() >= g.sides) { status_ = sRnf; finish(); return; }
        next_id_ = uint8_t(next_id_ % 16 + 1);
        buffer_[0] = cylinder_[d]; buffer_[1] = uint8_t(side()); buffer_[2] = next_id_; buffer_[3] = 1;
        const uint16_t crc = id_crc(buffer_);
        buffer_[4] = uint8_t(crc >> 8); buffer_[5] = uint8_t(crc);
        sector_ = cylinder_[d]; // The WD1793 copies the ID track into the sector register.
        op_ = Op::ReadAddress; position_ = 0; length_ = 6; busy_ = drq_ = true;
    }

    static uint16_t id_crc(const uint8_t* id) {
        uint16_t crc = 0xffff;
        const uint8_t mark[] = {0xa1, 0xa1, 0xa1, 0xfe, id[0], id[1], id[2], id[3]};
        for (uint8_t byte : mark) {
            crc ^= uint16_t(byte) << 8;
            for (unsigned i = 0; i < 8; ++i) crc = (crc & 0x8000) ? uint16_t((crc << 1) ^ 0x1021) : uint16_t(crc << 1);
        }
        return crc;
    }

    uint8_t read_data() {
        if ((op_ == Op::Read || op_ == Op::ReadAddress) && drq_) {
            data_ = buffer_[position_++];
            if (position_ == length_) {
                if (op_ == Op::Read && multiple_) {
                    ++sector_;
                    start_read(); // Ends with RNF past the last sector, as on a WD1793.
                } else {
                    finish();
                }
            }
        }
        return data_;
    }

    void write_data(uint8_t value) {
        data_ = value;
        if (!drq_) return;
        if (op_ == Op::Write) {
            buffer_[position_++] = value;
            if (position_ == 256) {
                if (!store_.write_sector(drive(), offset_, buffer_)) { status_ = sProtect; finish(); return; }
                ++sectors_written_;
                if (offset_ < 0x1000) forget_geometry(drive());
                if (multiple_) {
                    ++sector_;
                    if (!locate(offset_)) { status_ = sRnf; finish(); return; }
                    position_ = 0;
                } else {
                    finish();
                }
            }
        } else if (op_ == Op::WriteTrack) {
            format_byte(value);
        }
    }

    // Write Track (FORMAT): F5 writes an A1 sync mark, F7 the CRC. Collect
    // the four-byte ID after F5..FE and 256 data bytes after F5..FB.
    void format_byte(uint8_t value) {
        if (collecting_ > 0) {
            if (collecting_id_) {
                id_[4 - collecting_] = value;
                if (--collecting_ == 0) id_valid_ = true;
            } else {
                buffer_[256 - collecting_] = value;
                if (--collecting_ == 0) store_formatted_sector();
            }
        } else if (value == 0xf5) {
            synced_ = true;
        } else if (synced_ && value == 0xfe) {
            collecting_ = 4; collecting_id_ = true; id_valid_ = false; synced_ = false;
        } else if (synced_ && value == 0xfb && id_valid_) {
            collecting_ = 256; collecting_id_ = false; synced_ = false;
        } else {
            synced_ = false;
        }
        if (++position_ >= 6250) finish(); // One track at 250 kbit/s MFM.
    }
    void store_formatted_sector() {
        const unsigned d = drive(), cylinder = cylinder_[d], head = side();
        const Geometry g = geometry(d);
        const unsigned sector = id_[2];
        id_valid_ = false;
        if (cylinder >= g.cylinders || head >= g.sides || sector < 1 || sector > 16) return;
        const uint32_t offset = ((cylinder * g.sides + head) * 16u + sector - 1u) * 256u;
        if (store_.write_sector(d, offset, buffer_)) ++sectors_written_;
        if (offset < 0x1000) forget_geometry(d);
    }

    ZxDiskStore& store_;
    Op op_ = Op::None;
    bool busy_ = false, drq_ = false, intrq_ = false, type1_ = true, multiple_ = false;
    uint8_t status_ = 0, track_ = 0, sector_ = 1, data_ = 0, system_ = 0x3c, next_id_ = 0;
    int8_t direction_ = 1;
    uint8_t cylinder_[ZxDiskStore::drives] = {};
    uint8_t buffer_[256] = {};
    unsigned position_ = 0, length_ = 0;
    uint32_t offset_ = 0, command_revolution_ = 0;
    // Write Track parser.
    unsigned collecting_ = 0;
    bool collecting_id_ = false, synced_ = false, id_valid_ = false;
    uint8_t id_[4] = {};
    Geometry geometry_[ZxDiskStore::drives] = {};
    unsigned geometry_generation_[ZxDiskStore::drives] = {};
    uint32_t sectors_read_ = 0, sectors_written_ = 0;
};
