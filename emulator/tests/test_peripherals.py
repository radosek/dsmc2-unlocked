"""
Automated unit tests for RED DSMC2 Peripheral Hardware Models (M3, M5).
Tests GPTimer, UART, GPIO, Atmel maXTouch, EDID EEPROM, and Display Subsystem (DSS).
"""

import pytest

from emulator.devices.intc import OmapIntc
from emulator.devices.gptimer import OmapGPTimer
from emulator.devices.uart import OmapUart
from emulator.devices.gpio import OmapGpio
from emulator.devices.i2c_maxtouch import MaXTouchDevice
from emulator.devices.i2c_eeprom import EdidEeprom
from emulator.devices.dss import OmapDss


def test_intc_irq_assertion_and_masking():
    intc = OmapIntc()
    assert intc.has_pending_irq() is False

    # Assert IRQ 47 (Timer 11) - initially masked
    intc.assert_irq(47)
    assert intc.get_active_irq() is None # Masked by default

    # Unmask bank 1 (IRQs 32..63): unmask bit 15 (47 - 32 = 15)
    intc.mir[1] &= ~(1 << 15)
    assert intc.has_pending_irq() is True
    assert intc.get_active_irq() == 47

    # Acknowledge and clear via INTC_CONTROL (offset 0x48)
    intc.write(0x48, 4, 0x01)
    intc.deassert_irq(47)
    assert intc.has_pending_irq() is False


def test_gptimer_tick_and_overflow_irq():
    intc = OmapIntc()
    # Unmask Timer 11 IRQ (47)
    intc.mir[1] &= ~(1 << (47 - 32))

    timer = OmapGPTimer(11, 47, intc)
    timer.tldr = 0xFFFFFFF0 # Pre-load near overflow
    timer.tcrr = 0xFFFFFFF0
    timer.tier = 0x02       # Enable overflow interrupt (OVF_IT_FLAG)
    timer.tclr = 0x03       # Start timer with autoreload (ST=1, AR=1)

    assert intc.has_pending_irq() is False

    # Tick 20 steps to trigger overflow
    timer.tick(20)

    # Overflow should have asserted IRQ 47
    assert (timer.tisr & 0x02) != 0 # OVF flag set
    assert intc.has_pending_irq() is True
    assert intc.get_active_irq() == 47

    # Clear interrupt in timer TISR
    timer.write(0x18, 4, 0x02)
    assert (timer.tisr & 0x02) == 0


def test_uart_fifo_and_line_buffering():
    intc = OmapIntc()
    uart = OmapUart(4, 80, intc)

    # Status should show TX FIFO empty
    lsr = uart.read(0x14, 1) # LSR
    assert (lsr & 0x20) != 0 # THRE

    # Send a log line into UART TX
    for ch in b"RED DSMC2 System Ready\n":
        uart.write(0x00, 1, ch)

    assert len(uart.completed_lines) == 1
    assert uart.completed_lines[0] == "RED DSMC2 System Ready"

    # Inject data into RX FIFO
    uart.inject_rx_data(b"GET / PARAM ISO\n")
    lsr = uart.read(0x14, 1)
    assert (lsr & 0x01) != 0 # DR (Data Ready)
    assert uart.read(0x00, 1) == ord("G")


def test_gpio_pin_transitions_and_edge_detection():
    intc = OmapIntc()
    gpio = OmapGpio(1, 29, intc)

    # Configure Pin 12 as input with rising edge detection
    gpio.oe |= (1 << 12)          # Input
    gpio.risingdetect |= (1 << 12) # Rising edge
    gpio.irqenable1 |= (1 << 12)   # Interrupt enable

    # Level low -> no edge
    gpio.set_input_pin(12, False)
    assert (gpio.irqstatus1 & (1 << 12)) == 0

    # Level high -> rising edge triggered
    gpio.set_input_pin(12, True)
    assert (gpio.irqstatus1 & (1 << 12)) != 0
    assert (gpio.datain & (1 << 12)) != 0


def test_edid_eeprom_128_byte_structure():
    edid = EdidEeprom(0x50)
    data = edid.edid_data
    assert len(data) == 128

    # VESA EDID Header: 00 FF FF FF FF FF FF 00
    assert data[:8] == b"\x00\xFF\xFF\xFF\xFF\xFF\xFF\x00"

    # Checksum verification (sum of all 128 bytes must be 0 modulo 256)
    assert sum(data) % 256 == 0

    # Read descriptor string "RED TOUCH 7.0"
    assert b"RED TOUCH 7.0" in data

    # Sequential I2C byte reads
    edid.receive_bytes(bytes([0x00])) # Word address 0
    first_byte = edid.transmit_byte()
    assert first_byte == 0x00
    second_byte = edid.transmit_byte()
    assert second_byte == 0xFF


def test_maxtouch_touch_controller_protocol():
    maxtouch = MaXTouchDevice(0x4B)
    assert len(maxtouch.object_table) == 7 # T5, T6, T7, T8, T9, T15, T40

    # Inject touch event at (512, 288) (center of 1024x576 screen)
    maxtouch.inject_touch(512, 288, pressed=True)
    assert len(maxtouch.message_queue) > 0

    msg = maxtouch.message_queue[0]
    report_id = msg[0]
    status = msg[1]
    x = (msg[2] << 2) | ((msg[4] >> 6) & 0x03)
    y = (msg[3] << 2) | ((msg[4] >> 4) & 0x03)

    assert (status & 0x80) != 0 # DETECT bit
    assert (status & 0x40) != 0 # PRESS bit
    assert x == 512
    assert y == 288
