"""
OMAP3630 High-Speed UART (16550 compatible) Model.
Implements UART1..4 with interactive RX/TX FIFO buffers and interrupt signaling.
"""

from typing import Callable, Optional
from collections import deque
from emulator.core.bus import Device


class OmapUart(Device):
    """OMAP3630 16550-compatible High Speed UART."""

    def __init__(self, uart_num: int, irq_num: int, intc, on_tx_char: Optional[Callable[[str], None]] = None):
        self.uart_num = uart_num
        self.irq_num = irq_num
        self.intc = intc
        self.on_tx_char = on_tx_char

        self.rx_queue = deque()
        self.tx_history = []
        self.line_buffer = []
        self.completed_lines = []

        # 16550 Registers
        self.dll = 0x1A      # Baud divisor low
        self.dlh = 0x00      # Baud divisor high
        self.ier = 0x00      # Interrupt enable
        self.iir = 0x01      # Interrupt ID (0x01 = no interrupt pending)
        self.fcr = 0x00      # FIFO control
        self.efr = 0x00      # Enhanced feature register
        self.lcr = 0x03      # Line control (8N1)
        self.mcr = 0x00      # Modem control
        self.lsr = 0x60      # Line status (THRE | TEMT: Transmitter empty)
        self.msr = 0x00      # Modem status
        self.spr = 0x00      # Scratchpad
        self.mdr1 = 0x00     # Mode definition 1
        self.ssr = 0x03      # Supplementary status (TX FIFO empty)

    def write_rx(self, data: bytes):
        """Inject bytes into UART receiver."""
        for b in data:
            self.rx_queue.append(b)
        self.lsr |= 0x01 # Data Ready (DR)
        if (self.ier & 0x01) and self.intc: # RHR interrupt enabled
            self.intc.assert_irq(self.irq_num)

    inject_rx_data = write_rx

    def read(self, offset: int, size: int) -> int:
        dlab = bool(self.lcr & 0x80)
        mode_b = (self.lcr == 0xBF)

        if offset == 0x00:
            if dlab and not mode_b:
                return self.dll
            # RHR: Receive Holding Register
            if self.rx_queue:
                val = self.rx_queue.popleft()
                if not self.rx_queue:
                    self.lsr &= ~0x01 # No more data
                    if self.intc:
                        self.intc.deassert_irq(self.irq_num)
                return val
            return 0x00
        elif offset == 0x04:
            if dlab and not mode_b:
                return self.dlh
            return self.ier
        elif offset == 0x08:
            if mode_b:
                return self.efr
            return 0x01 # No interrupt pending
        elif offset == 0x0C:
            return self.lcr
        elif offset == 0x10:
            return self.mcr
        elif offset == 0x14: # LSR
            return self.lsr | (0x01 if self.rx_queue else 0x00)
        elif offset == 0x18:
            return self.msr
        elif offset == 0x1C:
            return self.spr
        elif offset == 0x20 or offset == 0x54: # MDR1
            return self.mdr1
        elif offset == 0x58: # SSR
            return self.ssr
        return 0

    def write(self, offset: int, size: int, value: int):
        val = value & 0xFF
        dlab = bool(self.lcr & 0x80)
        mode_b = (self.lcr == 0xBF)

        if offset == 0x00:
            if dlab and not mode_b:
                self.dll = val
            else:
                # THR: Transmit Holding Register
                ch = chr(val)
                self.tx_history.append(ch)
                if self.on_tx_char:
                    self.on_tx_char(ch)

                if ch == '\n':
                    line = "".join(self.line_buffer)
                    self.completed_lines.append(line)
                    self.line_buffer = []
                elif ch != '\r':
                    self.line_buffer.append(ch)
        elif offset == 0x04:
            if dlab and not mode_b:
                self.dlh = val
            else:
                self.ier = val
        elif offset == 0x08:
            if mode_b:
                self.efr = val
            else:
                self.fcr = val
        elif offset == 0x0C:
            self.lcr = val
        elif offset == 0x10:
            self.mcr = val
        elif offset == 0x1C:
            self.spr = val
        elif offset == 0x20 or offset == 0x54:
            self.mdr1 = val


UART_MAP = {
    1: (0x4806A000, 72),
    2: (0x4806C000, 73),
    3: (0x49020000, 74), # Camera CTRL / RCP port
    4: (0x49042000, 80), # System serial log / dsh> shell
}
