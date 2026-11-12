"""
Hardware I/O & Multi-Bus I2C Peripherals Test Suite.
Verifies TI TWL4030 PMIC, TI TMP411 Thermal, DSMC2 OLPF EEPROM, OMAP3630 GPMC Memory Controller,
and their integration with Dsmc2Camera, RedUiEngine, and Web Studio.
"""

import os
import json
import struct
import threading
import urllib.request
import pytest
from emulator.camera import Dsmc2Camera
from emulator.devices.i2c_pmic import Twl4030Pmic
from emulator.devices.i2c_thermal import Tmp411Thermal
from emulator.devices.i2c_olpf import OlpfEeprom
from emulator.devices.gpmc import OmapGpmc
from emulator.ui.redui import RedUiEngine
from emulator.ui.web import WebStudio, ThreadedHTTPServer, create_handler, find_free_port
from conftest import requires_firmware


@pytest.fixture
def workspace_root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


@pytest.fixture
def camera(workspace_root):
    cam = Dsmc2Camera(workspace_root)
    return cam


def test_pmic_twl4030_registers_and_voltage():
    """Verify TI TWL4030 PMIC I2C registers and MADC battery voltage conversion."""
    pmic = Twl4030Pmic(0x48)

    # Initial state
    assert pmic.address == 0x48
    assert pmic.is_dc_in_connected is True
    assert pmic.get_battery_voltage() == 14.8
    assert pmic.vdd1_mv == 1350
    assert pmic.vdd2_mv == 1150

    # Read VBUS status register
    vbus_bytes = pmic.read(pmic.REG_VBUS_STATUS, 1)
    assert vbus_bytes[0] == 0x07

    # Disconnect DC-IN
    pmic.set_dc_in(False)
    assert pmic.is_dc_in_connected is False
    vbus_bytes = pmic.read(pmic.REG_VBUS_STATUS, 1)
    assert vbus_bytes[0] == 0x00

    # Set Battery Voltage to 12.0V and verify ADC registers
    pmic.set_battery_voltage(12.0)
    assert pmic.get_battery_voltage() == 12.0
    msb_bytes = pmic.read(pmic.REG_MADC_VBAT_MSB, 2)
    adc_raw = (msb_bytes[0] << 2) | (msb_bytes[1] >> 6)
    expected_adc = min(1023, int((12000 / 16000.0) * 1023))
    assert adc_raw == expected_adc

    # Write register over I2C
    pmic.write(pmic.REG_POWER_STATUS, bytes([0x1F]))
    assert pmic.read(pmic.REG_POWER_STATUS, 1)[0] == 0x1F

    status = pmic.get_status()
    assert status["battery_voltage_v"] == 12.0
    assert status["dc_in_connected"] is False
    assert status["vdd1_v"] == 1.35
    assert status["vdd2_v"] == 1.15
    assert status["power_rails_active"] is True


def test_thermal_tmp411_registers_and_calibration():
    """Verify TI TMP411 dual-channel thermal sensor I2C transactions and T/E status."""
    thermal = Tmp411Thermal(0x4C)

    # Manufacturer & Revision ID
    assert thermal.read(thermal.REG_DEVICE_ID, 1)[0] == 0x41
    assert thermal.read(thermal.REG_CHIP_REV, 1)[0] == 0x11

    # Default temperatures: Sensor 39°C, Brain 63°C
    s_temp, b_temp = thermal.get_temperatures()
    assert s_temp == 39.0
    assert b_temp == 63.0
    assert thermal.is_calibrated_temperature() is True
    assert thermal.get_status_str() == "39°/63°"

    # Verify integer register reads
    assert thermal.read(thermal.REG_REMOTE_TEMP_MSB, 1)[0] == 39
    assert thermal.read(thermal.REG_LOCAL_TEMP_MSB, 1)[0] == 63

    # Update temperatures with fractional values
    thermal.set_temperatures(42.5, 68.25)
    assert thermal.get_temperatures() == (42.5, 68.25)
    assert thermal.read(thermal.REG_REMOTE_TEMP_MSB, 1)[0] == 42
    # 0.5 * 16 = 8 -> high nibble 0x80
    assert thermal.read(thermal.REG_REMOTE_TEMP_LSB, 1)[0] == 0x80

    # Temperature drift exceeds calibration target (39°C ± 2.5°C)
    assert thermal.is_calibrated_temperature() is False

    # Return to calibrated tolerance
    thermal.set_temperatures(40.0, 64.0)
    assert thermal.is_calibrated_temperature() is True


def test_olpf_eeprom_profiles_and_binary_serialization():
    """Verify DSMC2 OLPF 256-byte EEPROM magic header, profiles, and I2C reads."""
    olpf = OlpfEeprom(0x54, initial_type="Standard")
    assert olpf.address == 0x54
    assert olpf.get_olpf_type() == "Standard"

    # Header Magic: 'REDOLPF\x01'
    header = olpf.read(0x00, 8)
    assert header == b"REDOLPF\x01"

    # Type ID byte
    assert olpf.read(0x08, 1)[0] == 0x01

    # Name string null-terminated at offset 0x10
    raw_name = olpf.read(0x10, 32).split(b"\x00")[0].decode("utf-8")
    assert raw_name == "Standard OLPF"

    # 3x3 Color Matrix at offset 0x30
    matrix_bytes = olpf.read(0x30, 36)
    matrix = struct.unpack("<9f", matrix_bytes)
    assert len(matrix) == 9
    assert round(matrix[0], 2) == 1.02

    # Switch to Skin Tone-Highlight OLPF
    olpf.set_olpf_type("Skin Tone-Highlight")
    assert olpf.get_olpf_type() == "Skin Tone-Highlight"
    assert olpf.read(0x08, 1)[0] == 0x02
    skin_name = olpf.read(0x10, 32).split(b"\x00")[0].decode("utf-8")
    assert skin_name == "Skin Tone-Highlight"

    # Switch to Low Light Optimized
    olpf.set_olpf_type("Low Light Optimized")
    assert olpf.get_olpf_type() == "Low Light Optimized"
    assert olpf.read(0x08, 1)[0] == 0x03

    info = olpf.get_info()
    assert info["type_id"] == 0x03
    assert "Low Light" in info["type_name"]
    assert info["is_standard"] is False


def test_omap_gpmc_nand_and_bch_ecc():
    """Verify OMAP3630 GPMC memory-mapped controller, ONFI NAND commands, and BCH ECC."""
    gpmc = OmapGpmc()

    # SYSSTATUS: Reset Done
    assert gpmc.read(gpmc.REG_SYSSTATUS, 4) == 0x01

    # Reset
    gpmc.write(gpmc.REG_SYSCONFIG, 4, 0x02)
    assert gpmc.read(gpmc.REG_SYSSTATUS, 4) == 0x01

    # CS0 Config Registers
    assert gpmc.read(gpmc.REG_CONFIG1_0, 4) == 0x00000800
    assert gpmc.read(gpmc.REG_CONFIG7_0, 4) == 0x00000F48

    # ONFI NAND Command: Read ID (0x90)
    gpmc.write(gpmc.REG_NAND_CMD_0, 4, 0x90)
    word0 = gpmc.read(gpmc.REG_NAND_DATA_0, 4)
    assert word0 == 0xA590BA2C # Little-endian 32-bit: Byte 0=0x2C (Micron), Byte 1=0xBA (256MB SLC)
    byte4 = gpmc.read(gpmc.REG_NAND_DATA_0, 1)
    assert byte4 == 0x15

    # ONFI NAND Command: Read Status (0x70)
    gpmc.write(gpmc.REG_NAND_CMD_0, 4, 0x70)
    status_word = gpmc.read(gpmc.REG_NAND_DATA_0, 4)
    assert status_word == 0xE0

    # Hardware ECC accumulator
    gpmc.write(gpmc.REG_ECC_CONTROL, 4, 0x01) # Reset ECC
    assert gpmc.read(gpmc.REG_ECC1_RESULT, 4) == 0x00000000
    gpmc.write(gpmc.REG_NAND_DATA_0, 4, 0x12345678)
    assert gpmc.read(gpmc.REG_ECC1_RESULT, 4) == 0x12345678


def test_camera_hardware_bus_integration(camera):
    """Verify camera integrates multi-bus I2C topology and GPMC memory controller."""
    # 1. Bus I2C Allocation
    assert 1 in camera.i2c
    assert 2 in camera.i2c
    assert 3 in camera.i2c

    # I2C1 Slaves: PMIC (0x48), Thermal (0x4C)
    assert 0x48 in camera.i2c[1].slaves
    assert 0x4C in camera.i2c[1].slaves
    assert camera.i2c[1].slaves[0x48] is camera.pmic
    assert camera.i2c[1].slaves[0x4C] is camera.thermal

    # I2C2 Slaves: OLPF EEPROM (0x54)
    assert 0x54 in camera.i2c[2].slaves
    assert camera.i2c[2].slaves[0x54] is camera.olpf

    # I2C3 Slaves: maXTouch (0x4B), EDID (0x50)
    assert 0x4B in camera.i2c[3].slaves
    assert 0x50 in camera.i2c[3].slaves

    # GPMC Controller @ 0x6E000000
    assert hasattr(camera, "gpmc")
    gpmc_status = camera.bus.read_u32(0x6E000014)
    assert gpmc_status == 0x01

    # Camera helper methods
    camera.set_sensor_temperature(38.0, 62.0)
    assert camera.thermal.get_temperatures() == (38.0, 62.0)

    camera.set_battery_voltage(15.2)
    assert camera.pmic.get_battery_voltage() == 15.2

    success = camera.set_olpf_type("Skin Tone-Highlight")
    assert success is True
    assert camera.olpf.get_olpf_type() == "Skin Tone-Highlight"


def test_redui_olpf_and_project_status_integration(camera):
    """Verify RedUi monitor menu interacts with OLPF EEPROM and thermal monitor."""
    redui = RedUiEngine(camera)

    # Set thermal temperature
    camera.set_sensor_temperature(41.0, 65.0)

    # Check Project Status dynamic readout
    redui.menu_path = ["Menu", "SETTINGS", "MAINTENANCE", "System Status", "Project Status"]
    items = redui._get_current_items()
    temp_item = next(it for it in items if "Sensor Temp" in it)
    assert "41" in temp_item and "65" in temp_item

    # Navigate to OLPF Type selection
    redui.menu_path = ["Menu", "SETTINGS", "MAINTENANCE", "OLPF", "OLPF Type"]
    redui._handle_menu_item_selected("Low Light Optimized OLPF")

    # Verify EEPROM updated
    assert camera.olpf.get_olpf_type() == "Low Light Optimized"
    assert camera.olpf.read(0x08, 1)[0] == 0x03
    recent_logs = camera.get_serial_logs()
    assert any("[OLPF] I2C2 @ 0x54 EEPROM updated" in l for l in recent_logs)


@requires_firmware
def test_web_studio_hardware_endpoints(workspace_root):
    """Verify Web Studio hardware REST endpoints and live telemetry via HTTP."""
    test_port = find_free_port(9000)
    studio = WebStudio(workspace_root, host="127.0.0.1", port=test_port)
    studio.start_camera()

    handler = create_handler(studio)
    server = ThreadedHTTPServer(("127.0.0.1", test_port), handler)
    srv_thread = threading.Thread(target=server.serve_forever, daemon=True)
    srv_thread.start()

    base_url = f"http://127.0.0.1:{test_port}"

    try:
        # 1. Test GET /api/status telemetry contains hardware block
        resp = urllib.request.urlopen(f"{base_url}/api/status")
        assert resp.status == 200
        status = json.loads(resp.read().decode("utf-8"))
        assert "hardware" in status
        hw = status["hardware"]
        assert hw["pmic"]["battery_voltage_v"] == 14.8
        assert hw["thermal"]["sensor_c"] == 39.0
        assert hw["olpf"]["type_id"] == 1
        assert hw["gpmc"]["sysstatus"] == 1

        # 2. Test POST /api/hardware/thermal
        req = urllib.request.Request(
            f"{base_url}/api/hardware/thermal",
            data=json.dumps({"sensor_c": 44.5, "brain_c": 68.0}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        resp = urllib.request.urlopen(req)
        assert resp.status == 200
        t_data = json.loads(resp.read().decode("utf-8"))
        assert t_data["sensor_c"] == 44.5
        assert studio.camera.thermal.sensor_temp_c == 44.5

        # 3. Test POST /api/hardware/power
        req = urllib.request.Request(
            f"{base_url}/api/hardware/power",
            data=json.dumps({"voltage": 11.2, "dc_in": False}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        resp = urllib.request.urlopen(req)
        assert resp.status == 200
        p_data = json.loads(resp.read().decode("utf-8"))
        assert p_data["voltage"] == 11.2
        assert p_data["dc_in"] is False
        assert studio.camera.pmic.get_battery_voltage() == 11.2
        assert studio.camera.pmic.is_dc_in_connected is False

        # 4. Test POST /api/hardware/olpf
        req = urllib.request.Request(
            f"{base_url}/api/hardware/olpf",
            data=json.dumps({"type": "Skin Tone-Highlight"}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        resp = urllib.request.urlopen(req)
        assert resp.status == 200
        o_data = json.loads(resp.read().decode("utf-8"))
        assert o_data["status"] == "ok"
        assert o_data["olpf"]["type_id"] == 2
        assert studio.camera.olpf.get_olpf_type() == "Skin Tone-Highlight"

    finally:
        server.shutdown()
        studio.stop()
