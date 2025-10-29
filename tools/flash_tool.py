#!/usr/bin/env python3
import os, time, usb, usb.core, sys, io
import pyftdi, pyftdi.ftdi, pyftdi.eeprom, pyftdi.spi
from dataclasses import dataclass
# from pyftdi.ftdi import FtdiEeprom
from binascii import hexlify
import argparse


# Caravel housekeeping SPI pass-through prefix
HK_PASSTHRU = bytes([0xC4])  # enter flash pass-through until CSB release


# Flash command bytes (JEDEC-compatible NOR)
FL_WREN   = 0x06  # Write Enable
FL_WRDI   = 0x04
FL_RDSR   = 0x05  # Read Status
FL_RDID   = 0x9F  # Read JEDEC ID
FL_READ   = 0x03  # Read (slow)
FL_FASTRD = 0x0B  # Fast Read
FL_PP     = 0x02  # Page Program (256 B)
FL_SE     = 0x20  # Sector Erase 4 KiB
FL_BE64K  = 0xD8  # 64 KiB Block Erase
FL_CE     = 0xC7  # or 0x60 Chip Erase
FL_SFDP   = 0x5A  # Serial Flash Discoverable Properties

HK_CHIPID = 0x40  # 16 bit
HK_VERSION = 0x41 # 8 bit
HK_USER_ID = 0x42 # 32 bit

SR_WIP = 1 << 0
SR_WEL = 1 << 1

sfdp_table_ids = {
    0xFF00: "Basic SPI protocol",
    0xFF81: "Sector map",
    0xFF03: "Replay Protected Monotonic Counters (RPMC)",
    0xFF84: "4-byte Address Instruction Table",
    0xFF05: "eXtended Serial Peripheral Interface (xSPI) Profile 1.0",
    0xFF06: "eXtended Serial Peripheral Interface (xSPI) Profile 2.0",
    0xFF87: "Status, Control and Configuration Register Map",
    0xFF88: "Status, Control and Configuration Register Map Offsets for Multi-Chip SPI Memory Devices",
    0xFF09: "Status, Control and Configuration Register Map for xSPI Profile 2.0",
    0xFF0A: "Command Sequences to change to Octal DDR (8D-8D-8D) mode",
    0xFF8B: "Long Latency NVM Media Specific Parameter Table (MSPT)",
    0xFF0C: "x4 Quad IO with DS",
    0xFF8D: "Command Sequences to change to Quad DDR (4S-4D-4D) mode",
    0xFF8E: "Secure Packet Read / Secure Packet Write",
    0xFF0F: "Generic Register Access Method (GRAM) Parameter Table",
    0xFF90: "SPI Safety Extensions (CRC) Parameter Table",
    0xFF11: "SFDP CRC",
    0xFF12: "Error Correction Code (ECC) Parameter Table",
    0xFF93: "Reserved for next Function Specific Table assignment"
}
def caravel_xfer(port, bytes, read_len=0):
    res = port.exchange(bytes, read_len, duplex=False)
    return res

# --- helpers that wrap flash opcodes inside HK pass-through -------------------
def hk_xfer(port, payload: bytes, read_len=0):
    """
    Perform one HK pass-through transaction:
      assert CS -> send 0xC4 -> send payload -> optionally read -> deassert CS
    """
    if read_len:
        # write HK prefix + payload, then read bytes
        res = port.exchange(HK_PASSTHRU + payload, read_len, duplex=False)
        return res
    else:
        port.write(HK_PASSTHRU + payload)
        return b""

FLASH_TIMEOUT=1.0

def flash_status(port):
    return hk_xfer(port, bytes([FL_RDSR]), read_len=1)[0]

def flash_wait_ready(port, timeout=1.0):
    t0 = time.time()
    while True:
        status = flash_status(port)
        if not (status & SR_WIP): return
        if time.time() - t0 > timeout:
            raise TimeoutError("Flash WIP status did not clear withing timed out")
        time.sleep(0.005)

def flash_wren(port):
    hk_xfer(port, bytes([FL_WREN]))

def flash_read_sfdp(port, addr, len):
    cmd = bytes([ FL_SFDP, (addr>>16)&0xff, (addr>>8)&0xff, addr&0xff, 0x00 ])
    return hk_xfer(port, cmd, read_len=len)

def flash_read(port, addr, len):
    cmd = bytes([ FL_FASTRD, (addr>>16)&0xff, (addr>>8)&0xff, addr&0xff, 0x00 ])
    return hk_xfer(port, cmd, read_len=len)

def flash_page_program(port, addr, data):
    assert 1 <= len(data) <= 256
    flash_wren(port)
    payload = bytes([FL_PP, (addr>>16)&0xff, (addr>>8)&0xff, addr&0xff]) + data
    hk_xfer(port, payload)
    flash_wait_ready(port, timeout=FLASH_TIMEOUT)

def flash_sector_erase_4k(port, addr):
    flash_wren(port)
    payload = bytes([FL_SE, (addr>>16)&0xff, (addr>>8)&0xff, addr&0xff])
    hk_xfer(port, payload)
    flash_wait_ready(port, FLASH_TIMEOUT*3)

def aligned(a, align): return (a // align) * align

VERBOSE_LEVEL = 1
def log(level=1, *args, **kwargs):
    if level <= VERBOSE_LEVEL:
        print(*args, file=sys.stderr, **kwargs)

BLOCK:int = 256
SECTOR:int = 4096

@dataclass
class Tool:
    _usbdev:usb.core.Device = None
    _spiport:pyftdi.spi.SpiController = None
    _storage_size:int = 0 # zero if unknown

    def __init__(self):
        pass

    def setup(self, url):
        self._usbdev = pyftdi.ftdi.Ftdi.get_device(url)

    def reset_ftdi(self):
        ee = pyftdi.eeprom.FtdiEeprom()
        ee.open(self._usbdev)
        ee.reset_device()
       

    def flash_info(self):
        jedec = hk_xfer(self._spiport, bytes([FL_RDID]), read_len=3)
        log(2, f"JEDEC ID: {hexlify(jedec).decode()}  "
                f"(manf={jedec[0]:02X} mem={jedec[1]:02X} cap={jedec[2]:02X})")
        
        log(2, f">>> Reading SFDP")
        head = flash_read_sfdp(self._spiport, 0x0000, 8)
        if head[0:4] != b"SFDP":
            log(2, f"SFDP signature not found (found: {head[0:4].hex(' ')})")
        else:
            log(2, f"  signature: {head[0:4]}")
            log(2, f"  version: {head[5]}.{head[4]}")
            log(2, f"  access protocol: {head[7]}")
            log(2, f"  parameters: {head[6]}")
            param_count = int.from_bytes(head[6:7]) + 1
            ps = flash_read_sfdp(self._spiport, 0x0008, param_count * 8)
            for i in range(0, param_count):
                p = ps[i*8:i*8+8]
                tab_id = int.from_bytes([p[7], p[0]])
                tab_desc = sfdp_table_ids.get(tab_id, "<unknown>")
                tab_addr = int.from_bytes(p[4:7], byteorder='little')
                tab_words = p[3]
                log(2, f"  p[{i}] id 0x{tab_id:04x} ({tab_desc}) v{p[2]}.{p[1]} len words 0x{tab_words:0x} addr 0x{tab_addr:0x}")
                if tab_id == 0xff00:
                    basic = flash_read_sfdp(self._spiport, tab_addr, tab_words * 4)
                    for i in range(0, tab_words):
                        w = int.from_bytes(basic[i*4:i*4+4], byteorder='little')
                        log(2, f"    {i+1:02} 0x{w:08x}", end='')
                        if i == 1:
                            density = w+1 if (w&0x8000000) == 0 else 1<<(w&0x7ffffff)
                            self._storage_size = density>>3
                            log(2, f" memory density {density}/0x{density:08x} bits {density>>3} bytes")
                        else:
                            log(2, "")

    def open_spi(self):
        # open SPI connection
        # SPI_FREQ = 1000000
        SPI_FREQ = 100000
        spi = pyftdi.spi.SpiController()
        spi.configure(self._usbdev)
        self._spiport = spi.get_port(cs=0, freq=SPI_FREQ, mode=0)

        c_chipid = caravel_xfer(self._spiport, bytes([HK_CHIPID]), read_len=2)
        log(2, f"CHIPID: {int.from_bytes(c_chipid, 'big'):0x}")
        c_ver = caravel_xfer(self._spiport, bytes([HK_VERSION]), read_len=1)
        log(2, f"VERSION: {c_ver[0]:0x}")
        c_userid = caravel_xfer(self._spiport, bytes([HK_USER_ID]), read_len=4)
        log(2, f"USER ID: {int.from_bytes(c_userid, 'big'):0x}")

    def config_clock(self, cbus_index, cbus_func=None):
        # setup CBUS first
        ee = pyftdi.eeprom.FtdiEeprom()
        ee.open(self._usbdev)
        log(2, f"cbus pins: {' '.join(ee.cbus_pins)}")
        log(2, f"supported properties: {','.join(ee.properties)}")
        func = "CLK7_5"
        if cbus_func != None:
            func = cbus_func
        log(2, f"setting cbus_func_{cbus_index} to {func}")
        ee.set_property(f"cbus_func_{cbus_index}", func)
        ee.commit(dry_run=False)
        log(2, f"cbus pins (after set): {' '.join(ee.cbus_pins)}")

    def read_eeprom(self):
        ee = pyftdi.eeprom.FtdiEeprom()
        return ee.data
        eeprom = tool.read_eeprom()

    def erase(self, address, length):
        for a in range(0, length, SECTOR):
            flash_sector_erase_4k(self._spiport, address + a)

    def read(self, address, length, out):
        data = flash_read(self._spiport, address, length)
        out.write(data)

    def write(self, address, length, input):
        # erase
        for a in range(address, address + length, SECTOR):
            flash_wren(self._spiport)
            flash_sector_erase_4k(self._spiport, a)
        
        input.seek(0)
        # write
        for a in range(0, length, BLOCK):
            l = min(length - a, BLOCK)
            data = input.read(l)
            flash_wren(self._spiport)
            flash_page_program(self._spiport, address + a, data)

    def verify(self, address, length, input) -> int:
        mismatch = 0
        for a in range(0, length, BLOCK):
            l = min(length - a, BLOCK)
            data = input.read(l)
            flash_data = flash_read(self._spiport, address + a, l)
            for i, (a, b) in enumerate(zip(flash_data, data)):
                if a != b:
                    mismatch = mismatch + 1
                    log(1, f"Verify: MISMATCH at +0x{i:06X}: read 0x{a:02x} != exp 0x{b:02x}")
                    break
        return mismatch

if __name__ == "__main__":
    def auto_int(x:str) -> int:
        return int(x, 0) # base 0 --> autodetect base
    ap = argparse.ArgumentParser()
    ap.add_argument("command", type=str, default="info", nargs='?', choices=["read", "write", "erase", "read-eeprom", "set-clock", "reset-ftdi", "info"], help="Command to execute")
    ap.add_argument("-f", "--file", type=str, required=False, default="", help="File to operate on")
    ap.add_argument("-a", "--addr", type=auto_int, default=0, required=False, help="Memory address to read/write data")
    ap.add_argument("-l", "--length", type=auto_int, default=0, required=False, help="Lenght to read/write data. Memory size or file lenght when not specified")
    ap.add_argument("-u", "--url", type=str, default="ftdi://ftdi/1", required=False, help="FTDI device to connect to")
    ap.add_argument("-v", "--verbose", type=int, const=1, nargs='?', required=False, default=1, help="Verbose level (def 1)")
    ap.add_argument("-c", "--clock", type=str, required=False, help="Run CLK on CBUS pin. Format 'pin,CLK7_5'")
    # ap.add_argument("-clock", type=str, required=False, help="Run CLK on CBUS pin")
    args = ap.parse_args()

    # ftdi://[vendor][:[product][:serial | :bus:address | :index]]/interface
    # vendor: ftdi or VID like 0x403
    # product: alias (232h, 2232h, …) or PID like 0x6014
    # serial or bus:address or index: choose one selector
    # :serial = the device’s USB serial string
    # :bus:address = hex bus/address (e.g. :10:22 = bus 0x10, addr 0x22)
    # :index = nth matching device (least reliable)
    # /interface: FTDI interface number starting at 1 (FT232H uses 1)

    VERBOSE_LEVEL = args.verbose

    tool = Tool()
    tool.setup(args.url)

    mem_addr = args.addr
    mem_len = args.length
    if args.command == "read-eeprom":
        eeprom = tool.read_eeprom()
        print("eeprom: " + eeprom)
    elif args.command == "set-clock":
        a, b = args.clock.split(',')
        if a == "" or a == None:
            print(f"expecting --clock parameters, given: {args.clock}")
            exit(1)
        bus_index, clock_id = int(a), b
        tool.config_clock(bus_index, clock_id)
    elif args.command == "reset-ftdi":
        tool.reset_ftdi()
    else:
        tool.open_spi()
        if args.command == "info":
            tool.flash_info()
        elif args.command == "read":
            length = mem_len if args.length != 0 else tool._storage_size
            f_name = "<stdout>" if args.file=="" or args.file=='-' else args.file
            f = sys.stdout.buffer if args.file=="" or args.file=='-' else open(args.file, "wb")
            log(1, f"Reading {length} bytes at offset {mem_addr}, into {f_name}")
            tool.read(mem_addr, length, f)
        elif args.command == "write":
            copy = None
            is_file = args.file != "" and args.file != '-'
            length = 0
            f = None
            f_name = None
            if is_file:
                f = open(args.file, "rb")
                length = mem_len if mem_len else os.stat(args.file).st_size
                f_name = args.file
            else:
                copy = sys.stdin.buffer.read()
                f = io.BytesIO(copy)
                f_name = "<stdin>"
                length = len(copy)

            log(1, f"Writing {length} bytes at offset {mem_addr}, from {f_name}")
            tool.write(mem_addr, length, f)

            f.seek(0)
            log(1, f"Verifying {length} bytes at offset {mem_addr}, with contents of {f_name}")
            tool.verify(mem_addr, length, f)

        elif args.command == "erase":
            if mem_addr % SECTOR != 0:
                log(1, f"Erase address has to align on {SECTOR}")
            elif mem_len % SECTOR != 0:
                log(1, f"Erase length has to align on {SECTOR}")
            else:
                length = mem_len if mem_len else tool._storage_size
                log(1, f"Erasing from {mem_addr}, {length} bytes")
                tool.erase(mem_addr, length)

