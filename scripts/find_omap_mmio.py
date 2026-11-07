import os
import struct
import capstone

path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "firmware_store", "unpacked", "scarlet_w_7_4_1", "slot", "dsmc_program.mem")
data = open(path, "rb").read()

md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)
md.detail = True

# Search for functions referencing OMAP / DM37xx registers:
# Standard OMAP3 peripherals:
# 0x48002000: Control module
# 0x48004000: PRCM
# 0x48050000..0x4805ffff: DSS
# 0x48060000: I2C3
# 0x48070000: I2C1
# 0x48072000: I2C2
# 0x4806a000: UART1
# 0x4806c000: UART2
# 0x4806e000: UART3
# 0x48200000: INTC (Interrupt Controller)
# 0x48310000: GPIO1
# 0x48318000: GPTimer1
# 0x49050000: GPIO2
# 0x49052000: GPIO3
# 0x49054000: GPIO4
# 0x49056000: GPIO5
# 0x49058000: GPIO6
# 0x6e000000: GPMC

omap_bases = {
    0x48002000: "CONTROL_MODULE",
    0x48004000: "PRCM",
    0x48050000: "DSS_DISPC",
    0x48056000: "DSS_DSI",
    0x48060000: "I2C3",
    0x48070000: "I2C1",
    0x48072000: "I2C2",
    0x4806a000: "UART1",
    0x4806c000: "UART2",
    0x4806e000: "UART3",
    0x49020000: "UART3_OMAP3630",
    0x48098000: "McSPI1",
    0x4809a000: "McSPI2",
    0x480b8000: "McSPI3",
    0x480ba000: "McSPI4",
    0x48200000: "INTC_MPU",
    0x48310000: "GPIO1",
    0x48318000: "GPTIMER1",
    0x49032000: "GPTIMER2",
    0x49034000: "GPTIMER3",
    0x4903e000: "GPTIMER10",
    0x49050000: "GPIO2",
    0x49052000: "GPIO3",
    0x49054000: "GPIO4",
    0x49056000: "GPIO5",
    0x49058000: "GPIO6",
    0x6e000000: "GPMC",
    0x6d000000: "SDRC",
}

found = {}
for base, name in omap_bases.items():
    pattern = struct.pack("<I", base)
    offsets = []
    pos = 0
    while True:
        idx = data.find(pattern, pos)
        if idx == -1:
            break
        offsets.append(idx)
        pos = idx + 4
    if offsets:
        found[base] = (name, len(offsets), offsets[:3])

print("Confirmed OMAP3 / DM37xx MMIO bases in dsmc_program.mem:")
for base, (name, count, sample_offsets) in sorted(found.items()):
    samples = ", ".join(f"VA 0x{0x80000000+o:08x}" for o in sample_offsets)
    print(f"  0x{base:08x} ({name:20}): {count:3d} refs ({samples})")
