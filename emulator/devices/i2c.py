"""
OMAP3630 I2C Controller Model with Virtual Bus and Peripheral Routing.
Implements I2C1, I2C2, I2C3 with slave device attachment.
"""

from typing import Dict, Optional, Callable
from collections import deque
from emulator.core.bus import Device


class I2cSlave:
    """Base class for I2C slave devices."""
    def __init__(self, address: int):
        self.address = address

    def read(self, reg_addr: int, length: int) -> bytes:
        return b"\x00" * length

    def write(self, reg_addr: int, data: bytes) -> bool:
        return True


class OmapI2c(Device):
    """OMAP3630 I2C Master Controller."""

    def __init__(self, bus_id: int, irq_num: int, intc):
        self.bus_id = bus_id
        self.irq_num = irq_num
        self.intc = intc
        self.slaves: Dict[int, I2cSlave] = {}

        # Registers
        self.rev = 0x36
        self.ie = 0x0000
        self.stat = 0x0000
        self.syss = 0x0001 # RDONE = 1
        self.buf = 0x0000
        self.cnt = 0
        self.sysc = 0x0000
        self.con = 0x0000
        self.oa = 0x0000
        self.sa = 0x0000
        self.psc = 0
        self.scll = 0
        self.sclh = 0

        # Transfer queues
        self.tx_fifo = deque()
        self.rx_fifo = deque()
        self.current_reg_addr = 0
        self.force_nack: bool = False
        self.on_transaction_finished: Optional[Callable] = None

    @property
    def i2c_stat(self) -> int:
        return self.stat

    @i2c_stat.setter
    def i2c_stat(self, val: int):
        self.stat = val

    def attach_slave(self, slave: I2cSlave):
        self.slaves[slave.address] = slave

    def read(self, offset: int, size: int) -> int:
        if offset == 0x00: # REV
            return self.rev
        elif offset == 0x04: # IE
            return self.ie
        elif offset == 0x08: # STAT
            return self.stat
        elif offset == 0x10: # SYSS
            return self.syss
        elif offset == 0x14: # BUF
            rx_count = len(self.rx_fifo)
            rx_stat = max(0, rx_count - 1) & 0x3F
            tx_remaining = max(0, self.cnt - len(self.tx_fifo))
            tx_stat = max(0, tx_remaining - 1) & 0x3F
            return (self.buf & ~0x3F3F) | (rx_stat << 8) | tx_stat
        elif offset == 0x18: # CNT
            return self.cnt
        elif offset == 0x1C: # DATA (RRDY / FIFO read)
            if self.rx_fifo:
                val = self.rx_fifo.popleft()
                if not self.rx_fifo:
                    self.stat &= ~0x08 # Clear RRDY
                    self.stat |= 0x04  # Assert ARDY (transfer complete)
                    if (self.ie & 0x04) and self.intc:
                        self.intc.assert_irq(self.irq_num)
                return val
            return 0x00
        elif offset == 0x20: # SYSC
            return self.sysc
        elif offset == 0x24: # CON
            return self.con
        elif offset == 0x28: # OA
            return self.oa
        elif offset == 0x2C: # SA
            return self.sa
        elif offset == 0x30: # PSC
            return self.psc
        elif offset == 0x34: # SCLL
            return self.scll
        elif offset == 0x38: # SCLH
            return self.sclh
        return 0

    def write(self, offset: int, size: int, value: int):
        val = value & 0xFFFF
        if offset == 0x04: # IE
            self.ie = val
        elif offset == 0x08: # STAT (write 1 to clear)
            self.stat &= ~val
            if val & 0x04: # Clearing ARDY clears TX FIFO
                self.tx_fifo.clear()
            if not (self.stat & self.ie) and self.intc:
                self.intc.deassert_irq(self.irq_num)
        elif offset == 0x14: # BUF
            self.buf = val
        elif offset == 0x18: # CNT
            self.cnt = val
        elif offset == 0x1C: # DATA (TX FIFO write)
            byte_val = val & 0xFF
            self.tx_fifo.append(byte_val)
            if self.cnt > 0 and len(self.tx_fifo) >= self.cnt:
                slave = self.slaves.get(self.sa)
                fifo_list = list(self.tx_fifo)
                if slave and bool(self.con & 0x0200): # Master Transmit
                    if len(fifo_list) == 1:
                        self.current_reg_addr = fifo_list[0]
                    else:
                        self.current_reg_addr = fifo_list[0]
                        slave.write(self.current_reg_addr, bytes(fifo_list[1:]))
                self.stat |= 0x04 # ARDY
                self.stat &= ~0x10 # Clear XRDY
                if (self.ie & 0x04) and self.intc:
                    self.intc.assert_irq(self.irq_num)
        elif offset == 0x20: # SYSC
            self.sysc = val
            if val & 0x02: # Software reset
                self.syss = 0x01 # Reset done
        elif offset == 0x24: # CON
            self.con = val
            if (val & 0x8000) and (val & 0x01): # EN & STT (Start transaction)
                self._execute_transaction(val)
        elif offset == 0x28: # OA
            self.oa = val
        elif offset == 0x2C: # SA
            self.sa = val
        elif offset == 0x30:
            self.psc = val
        elif offset == 0x34:
            self.scll = val
        elif offset == 0x38:
            self.sclh = val

    def _execute_transaction(self, con_val: int):
        """Process I2C master transfer."""
        is_tx = bool(con_val & 0x0200) # TRX bit
        slave_addr = self.sa
        byte_count = self.cnt

        slave = self.slaves.get(slave_addr)

        if slave is None or self.force_nack:
            # NACK if no slave at target address or forced NACK condition
            self.stat |= 0x02 # NACK
            if self.ie & 0x02 and self.intc:
                self.intc.assert_irq(self.irq_num)
            return

        if is_tx:
            # Master Transmit
            slave = self.slaves.get(slave_addr)
            if self.cnt > 0 and len(self.tx_fifo) >= self.cnt:
                # Pre-loaded TX FIFO: commit transmit immediately
                fifo_list = list(self.tx_fifo)
                if slave:
                    if len(fifo_list) == 1:
                        self.current_reg_addr = fifo_list[0]
                    else:
                        self.current_reg_addr = fifo_list[0]
                        slave.write(self.current_reg_addr, bytes(fifo_list[1:]))
                self.stat |= 0x04 # ARDY
                self.stat &= ~0x10 # Clear XRDY
                if (self.ie & 0x04) and self.intc:
                    self.intc.assert_irq(self.irq_num)
            elif self.cnt > 0:
                self.tx_fifo.clear()
                self.stat |= 0x10 # XRDY (Request TX data from CPU)
                self.stat &= ~0x04
                if (self.ie & 0x10) and self.intc:
                    self.intc.assert_irq(self.irq_num)
            else:
                self.tx_fifo.clear()
                self.stat |= 0x04 # ARDY (Empty transfer complete)
                if (self.ie & 0x04) and self.intc:
                    self.intc.assert_irq(self.irq_num)
        else:
            # Master Receive: fetch bytes from slave
            count = byte_count if byte_count > 0 else 1
            rx_bytes = slave.read(self.current_reg_addr, count)
            self.rx_fifo.clear()
            for b in rx_bytes:
                self.rx_fifo.append(b)
            if self.rx_fifo:
                self.stat |= 0x08 # RRDY (Data Ready)
                # Two-phase receive: ARDY will be asserted when the CPU drains rx_fifo via 0x1C
                if (self.ie & 0x08) and self.intc:
                    self.intc.assert_irq(self.irq_num)
            else:
                self.stat |= 0x04 # ARDY (Empty transfer complete)
                if (self.ie & 0x04) and self.intc:
                    self.intc.assert_irq(self.irq_num)

        if self.on_transaction_finished:
            self.on_transaction_finished(slave_addr, is_tx, byte_count)


I2C_MAP = {
    1: (0x48070000, 56),
    2: (0x48072000, 57),
    3: (0x48060000, 61), # Peripherals: Touch, Sensors, Monitor
}
