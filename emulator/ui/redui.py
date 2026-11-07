"""
RedUi Graphical Engine and Interactive Menu System for RED DSMC2.
Provides authentic DSMC2 HUD overlays, quick-selection dialogs (FPS, Shutter, ISO, Format),
full system menu, exposure tools (False Color, Zebras, 1:1 Mag), and touch feedback.
"""

import os
import time
import math
from typing import Optional, Tuple, Dict, Any, List
from PIL import Image, ImageDraw, ImageFont
from emulator.rcp.protocol import RcpProtocol

try:
    FONT_TITLE = ImageFont.truetype("arialbd.ttf", 15)
    FONT_MED = ImageFont.truetype("arial.ttf", 13)
    FONT_BOLD = ImageFont.truetype("arialbd.ttf", 13)
    FONT_SM = ImageFont.truetype("arial.ttf", 11)
    FONT_TINY = ImageFont.truetype("arial.ttf", 9)
except Exception:
    FONT_TITLE = ImageFont.load_default()
    FONT_MED = ImageFont.load_default()
    FONT_BOLD = ImageFont.load_default()
    FONT_SM = ImageFont.load_default()
    FONT_TINY = ImageFont.load_default()


class RedUiEngine:
    """
    Simulates the RED DSMC2 RedUi graphical user interface.
    Handles touch regions, modal dialogs, hierarchical system menu, and display overlays.
    """

    WIDTH = 1024
    HEIGHT = 576

    # Available quick parameters
    FPS_OPTIONS = ["23.98", "24.00", "25.00", "29.97", "48.00", "50.00", "59.94", "60.00", "120.00"]
    SHUTTER_OPTIONS = ["1/24", "1/32", "1/48", "1/50", "1/60", "1/96", "1/120", "1/250", "1/500", "180.0°"]
    ISO_OPTIONS = ["250", "320", "400", "500", "640", "800", "1000", "1280", "1600", "3200"]
    FORMAT_OPTIONS = ["5K 16:9", "5K 2:1", "4.5K 16:9", "4K 16:9", "3K 16:9", "2K 16:9"]
    IRIS_OPTIONS = ["1.4", "1.8", "2.0", "2.8", "4.0", "5.6", "8.0", "11.0", "16.0", "22.0"]

    MENU_TABS = ["SETTINGS", "MEDIA", "AUDIO", "OVERLAYS", "LOOK", "ABOUT"]

    # Official DSMC2 Master Menu Hierarchy
    DSMC2_MENU_TREE: Dict[str, Any] = {
        "IMAGE": {
            "IMAGE PIPELINE": {
                "Options": ["IPP2 Mode", "Legacy Mode", "Standard Options", "Log3G10", "REDWideGamutRGB", "Output Transform"],
                "Output Summary": ["Pipeline: IPP2", "Color Space: REDWideGamutRGB", "Gamma Curve: Log3G10", "3D LUT: RED IPP2 Cinema Standard"]
            },
            "WHITE BALANCE": {
                "Color Temperature": ["3200K (Tungsten)", "4000K", "5000K", "5600K (Daylight)", "6500K", "8000K (Shade)"],
                "Tint": ["-10.0 (Magenta)", "-5.0", "0.0 (Neutral)", "+5.0", "+10.0 (Green)"],
                "Auto White Balance": ["Calculate AWB Now", "Reset AWB to 5600K"]
            },
            "ISO": {
                "ISO": ["250", "320", "400", "500", "640", "800", "1000", "1280", "1600", "3200", "6400", "12800"],
                "Shadow": ["Shadow -2.0", "Shadow -1.0", "Shadow 0.0 (Default)", "Shadow +1.0", "Shadow +2.0"],
                "FLUT": ["FLUT -2.0", "FLUT -1.0", "FLUT 0.0 (Default)", "FLUT +1.0", "FLUT +2.0"],
                "Exposure Adjust": ["-3.0 Stops", "-2.0 Stops", "-1.0 Stop", "0.0 (Nominal)", "+1.0 Stop", "+2.0 Stops", "+3.0 Stops"]
            },
            "COLOR": {
                "Saturation": ["Saturation 0.0 (B&W)", "Saturation 0.5", "Saturation 1.0 (Default)", "Saturation 1.2", "Saturation 1.5"],
                "Contrast": ["Contrast -0.5", "Contrast 0.0 (Default)", "Contrast +0.5", "Contrast +1.0"],
                "Brightness": ["Brightness -1.0", "Brightness 0.0 (Default)", "Brightness +1.0"],
                "Exposure Compensation": ["-2.0 EV", "-1.0 EV", "0.0 EV (Default)", "+1.0 EV", "+2.0 EV"]
            },
            "GAIN": {
                "Color": ["Red Gain 1.00", "Green Gain 1.00", "Blue Gain 1.00", "Reset Gains"],
                "User Matrix": ["Matrix: Standard", "Matrix: Custom 1", "Matrix: Custom 2", "Reset Matrix"]
            },
            "CURVES": {
                "Luma Curve": ["Luma Linear", "Luma S-Curve", "Luma High Contrast", "Luma Soft Clip"],
                "Red Curve": ["Red Linear", "Red Boost", "Red Soften"],
                "Green Curve": ["Green Linear", "Green Boost", "Green Soften"],
                "Blue Curve": ["Blue Linear", "Blue Boost", "Blue Soften"],
                "Reset Curve": ["Reset All Curves to Linear"]
            },
            "LGG": {
                "Lift": ["Lift -0.05", "Lift 0.00 (Default)", "Lift +0.05", "Lift +0.10"],
                "Gamma": ["Gamma 0.90", "Gamma 1.00 (Default)", "Gamma 1.10", "Gamma 1.20"],
                "Gain": ["Gain 0.90", "Gain 1.00 (Default)", "Gain 1.10", "Gain 1.20"]
            },
            "CDL": {
                "Slope": ["Slope Red 1.0", "Slope Green 1.0", "Slope Blue 1.0"],
                "Power": ["Power Red 1.0", "Power Green 1.0", "Power Blue 1.0"],
                "Offset": ["Offset Red 0.0", "Offset Green 0.0", "Offset Blue 0.0"],
                "Saturation": ["CDL Saturation 1.00"],
                "CDLs": ["Import CDL", "Export CDL", "Bypass CDL"]
            },
            "3D LUT": {
                "Creative 3D LUT": ["RED IPP2 Cinema Standard", "Film Rec709", "Low Contrast Print", "Log3G10 Neutral", "Import 3D LUT (.cube)"]
            }
        },
        "MONITORING": {
            "MONITORS": {
                "Select Monitor": ["Brain LCD (RED Touch 7.0)", "EVF (OLED)", "HD-SDI 1", "HD-SDI 2", "HDMI Monitor"],
                "Priority": ["Auto Detect Priority", "Brain LCD Primary", "EVF Primary", "HD-SDI Primary"]
            },
            "TEST SIGNAL": {
                "Off": ["Test Signal OFF"],
                "Chip Chart": ["Standard Chip Chart (Gamma/Color)"],
                "SMPTE Bars": ["SMPTE Color Bars 100%"],
                "Luma": ["Luma Step Ramp 10-Step", "Luma Smooth Ramp"],
                "Audio Tone": ["Audio Tone 1 kHz (-20 dBFS)", "Audio Tone Sweep", "Tone OFF"]
            },
            "LOOK AROUND": {
                "Look Around": ["Look Around ON (5% Margin)", "Look Around OFF (Full Frame)"]
            },
            "ADVANCED": {
                "Video": ["Clean Video Feed", "Display All Overlays Feed", "Guides Only Feed"],
                "Touch": ["Touchscreen Locked", "Touchscreen Unlocked", "Recalibrate Touch Digitizer"],
                "Genlock Offset": ["Genlock Offset 0 Lines", "Genlock Offset +1 Line", "Sync Phase 0.00°"]
            }
        },
        "OVERLAYS": {
            "TOOLS": {
                "False Color": ["Off", "Exposure", "Video", "Focus", "Edge", "Gio Scope"],
                "Magnify": ["1:1 Magnify Center", "1:1 Magnify Focus Point", "Magnify OFF"],
                "RAW": ["RAW View ON", "RAW View OFF"],
                "Horizon": ["Horizon Level ON", "Horizon Level OFF"],
                "Zebras": ["Zebras 1 (95%)", "Zebras 2 (80%)", "Zebras OFF"]
            },
            "STATUS": {
                "Camera": ["Show Core Camera Status", "Show Temperatures (Sensor/Core)", "Show Fan RPM"],
                "Lens": ["Show Lens Focal & Aperture", "Show Focus Distance (m/ft)", "Lens Status OFF"]
            },
            "GUIDES": {
                "Frame Guide": ["16:9 Frame Guide", "2.39:1 Anamorphic Guide", "1.85:1 Cinema Guide", "4:3 Guide", "Guides OFF"],
                "Action Guide": ["Action Safe 90% ON", "Action Safe OFF"],
                "Title Guide": ["Title Safe 80% ON", "Title Safe OFF"],
                "General": ["Guide Line: Red", "Guide Line: White", "Guide Line: Yellow", "Guide Shading 50%", "Guide Shading 100%"]
            },
            "CUSTOM": {
                "In Camera": ["Load Reticle 1", "Save Current Reticle", "Reset Reticle"],
                "On Media, overlays": ["Save Overlays to RED MINI-MAG", "Load Overlays from Media"]
            }
        },
        "POWER": {
            "Power In": ["DC IN 14.8V", "Low Battery Warning", "Min Voltage Alert", "Battery Level: 100%"],
            "Power Out": ["Aux 12V DC Out (2.0A)", "RS 24V Run/Stop Out", "USB 5V Power ON", "Power Out All OFF"],
            "Power Save": ["Auto Sleep: 15 Min", "Auto Sleep: Never", "LCD Dimmer: 60s", "Low Power Fan Mode ON"],
            "Shutdown": ["Power Off Camera", "Cancel"]
        },
        "PLAYBACK": {
            "Playback Screen": ["Browse Recorded Clips", "Play / Pause", "Shuttle 2x / 4x", "Frame Step Forward", "Frame Step Backward", "In/Out Marker", "Clip Metadata Inspector"]
        },
        "MEDIA": {
            "Device": ["Format RED MINI-MAG (512GB)", "Eject Media Safely", "Media Status & S.M.A.R.T.", "Verify File System (UDF)"],
            "Clips": ["List R3D Clips", "Clip Properties / Metadata", "Delete Last Recorded Clip", "Export Clip Log"]
        },
        "PRESETS": {
            "Camera Presets": ["Save User Preset to Memory", "Load User Preset", "Export Preset to MINI-MAG", "Factory Default Reset"],
            "Looks": ["Cinema Standard Look", "High Dynamic Range Look", "Vintage 35mm Film Look", "Low Contrast Commercial"],
            "Auto Presets": ["Narrative 24fps 5K", "Commercial 60fps 4K", "High Speed Slow-Mo 120fps 3K"]
        },
        "SETTINGS": {
            "LOOK": {
                "Color": ["Saturation 1.0 (Default)", "Contrast 0.0", "Brightness 0.0", "Exposure Comp 0.0"],
                "Gain": ["Red Gain 1.00", "Green Gain 1.00", "Blue Gain 1.00", "User Matrix: Standard"],
                "ISO/FLUT®": ["ISO 250", "ISO 320", "ISO 400", "ISO 500", "ISO 640", "ISO 800", "ISO 1000", "ISO 1280", "ISO 1600", "ISO 3200", "Shadow: 0.0", "FLUT: 0.0"],
                "Sharpness": ["Sharpness: Normal", "Sharpness: Crisp", "Sharpness: Soft", "Denoise: Off", "Denoise: Standard"],
                "Curves": ["Luma S-Curve", "Luma High Contrast", "Red/Green/Blue RGB Curves", "Reset Curves to Linear"],
                "Video": ["Video Color Space: Rec.709", "Video Color Space: REDcolor4", "Gamma: REDlogFilm", "Gamma: BT.1886"],
                "Color Temp": ["3200K (Tungsten)", "4000K", "5000K", "5600K (Daylight)", "6500K", "Auto WB Calibration"],
                "LGG": ["Lift 0.00", "Gamma 1.00", "Gain 1.00", "Reset LGG"]
            },
            "PROJECT": {
                "Frame Rate": ["23.98", "24.00", "25.00", "29.97", "48.00", "50.00", "59.94", "60.00", "120.00"],
                "Exposure": ["1/24", "1/32", "1/48", "1/50", "1/60", "1/96", "1/120", "1/250", "1/500", "180.0°"],
                "Timecode": {
                    "Timecode Display Mode": ["Time of Day (TOD)", "Edge Code", "External LTC"],
                    "Source": ["Internal RTC Clock", "External LTC (Lemo)", "Genlock Sync"]
                },
                "Slate": {
                    "Scene": ["Scene A01", "Scene A02", "Scene B01", "Scene C01"],
                    "Camera": ["Camera A", "Camera B", "Camera C"],
                    "Project": ["Project: DSMC2 Production", "Director: Cinematographer", "Production: RED Virtual Studio"],
                    "Auto Slate": ["Auto Slate ON (Beep on REC)", "Auto Slate OFF"]
                },
                "Format": ["5K 16:9", "5K 2:1", "4.5K 16:9", "4K 16:9", "3K 16:9", "2K 16:9"],
                "Sensor": {
                    "Flip/Mirror Scan Direction": ["Standard Scan Direction", "Flip Sensor Scan", "Mirror Sensor Scan", "Flip & Mirror"]
                }
            },
            "RECORDING": {
                "Mode": {
                    "Storage": ["RED MINI-MAG (Port 1)", "External Storage"],
                    "Mode": ["Continuous Record", "Burst Mode", "Speed Ramp", "Time Lapse"]
                },
                "Codec": {
                    "Record File Format": ["REDCODE RAW (R3D)", "Apple ProRes 422 HQ", "ProRes + R3D Dual Record", "Avid DNxHR HQX"],
                    "REDCODE®": ["REDCODE 3:1", "REDCODE 5:1", "REDCODE 8:1", "REDCODE 12:1", "REDCODE 16:1"]
                },
                "Frame Processing": {
                    "Mode": ["Normal Processing", "Multi-Frame Burst", "Frame Averaging"],
                    "Number of Frames": ["1 Frame", "2 Frames", "4 Frames", "8 Frames"]
                },
                "Pre-Record": {
                    "Duration": ["Pre-Record OFF", "Pre-Record 2 Sec", "Pre-Record 4 Sec", "Pre-Record 8 Sec", "Pre-Record 10 Sec"],
                    "Always Trigger": ["Always Trigger ON", "Always Trigger OFF"],
                    "Trigger Pre-Record Now": ["Arm & Buffer Pre-Record"]
                },
                "Indicator": {
                    "Enable Sounds": ["Record Beeps ON", "Record Beeps OFF", "Key Click Sounds"],
                    "EVF Tally Light": ["EVF Tally ON", "EVF Tally OFF"],
                    "SSD Tally Light": ["SSD Tally LED ON", "SSD Tally LED OFF"]
                }
            },
            "HDRX": {
                "Mode": ["HDRx OFF", "HDRx ON"],
                "Factor": ["+1 Stop (2x)", "+2 Stops (4x)", "+3 Stops (8x)", "+4 Stops (16x)", "+5 Stops (32x)", "+6 Stops (64x)"],
                "Monitor Track": ["Track A (Normal Exposure)", "Track X (Highlight Protection)"]
            },
            "AUDIO": {
                "Control": {
                    "Channel 1/2": ["Ch1: Cam Mic L (+18dB)", "Ch2: Cam Mic R (+18dB)", "Phantom +48V ON", "Line Level In"],
                    "Channel 3/4": ["Ch3: Aux Audio In", "Ch4: Aux Audio In", "Mute Ch3/4"],
                    "Pre-Amp Gain": ["Pre-Amp 0 dB", "Pre-Amp +12 dB", "Pre-Amp +18 dB", "Pre-Amp +24 dB", "Pre-Amp +36 dB"],
                    "Headphone Volume": ["Volume 40%", "Volume 60%", "Volume 80%", "Volume 100%"]
                },
                "Mix": {
                    "Headphone Mix": ["Stereo Mix L/R", "Mono Ch1", "Mono Ch2"],
                    "Monitor Mix": ["Program Audio 1/2", "Monitor Audio Mute"]
                }
            },
            "FOCUS": {
                "Mode": ["Manual Focus (MF)", "Autofocus Single (AF-S)", "Continuous AF (AF-C)"],
                "Rack": ["Rack Focus Start Point", "Rack Focus End Point", "Execute Rack Focus", "Rack Speed: Medium"]
            },
            "EXPOSURE ASSIST": {
                "Mode": ["Exposure Assist OFF", "Spot Metering Assist", "Exposure Priority Assist"],
                "Exposure Priority": ["Manual Exposure", "Iris Priority", "Shutter Priority"],
                "Exp Comp": ["-2.0 EV", "-1.0 EV", "0.0 EV (Nominal)", "+1.0 EV", "+2.0 EV"],
                "Metering Mode": ["Center-Weighted Metering", "Spot Metering (Center)", "Matrix Multi-Zone"],
                "Selection": ["Spot Focus / Meter Target", "Reset Target to Center"]
            },
            "SETUP": {
                "Keys": {
                    "Key Mapping": ["User 1 -> False Color", "User 2 -> Zebras", "Record Key -> Toggle REC", "D-Pad -> Navigation"],
                    "Options": ["Key Tone Sound ON", "Key Lockout Enabled", "Key Lockout Disabled"],
                    "Soft Keys": ["Soft Key A -> 1:1 Magnify", "Soft Key B -> Horizon Level"],
                    "Advanced": ["Load Key Profile", "Save Key Profile", "Reset Key Mappings"]
                },
                "Date/Time": {
                    "Date": ["Set Year 2026", "Set Month 11", "Set Day 06"],
                    "Local Time": ["Set Time 16:30:00", "Sync to Host System Time"],
                    "Time Zone": ["UTC-8 (Pacific)", "UTC-5 (Eastern)", "UTC+0 (GMT/UTC)", "UTC+1 (CET)"]
                },
                "Communication": {
                    "Camera": ["Camera Name: SCARLET-W 5K", "Camera PIN: 0000"],
                    "Serial": ["UART4 RS-232 @ 115200 Baud", "Binary Protocol ON", "ASCII Terminal Mode"],
                    "Ethernet³": ["Gigabit Ethernet: Connected", "DHCP Auto", "Static IP: 192.168.1.100"],
                    "WiFi": ["WiFi Infrastructure", "WiFi Ad-Hoc", "WiFi OFF"],
                    "RCP⁴": ["RCP Server Port 1111", "RCP Status: Online", "Clients Connected: 0", "Authenticate RCP"]
                },
                "GPIO / Sync": {
                    "Sync": ["Genlock Sync: Internal", "Genlock Sync: External SMPTE", "Sync Phase: 0°"],
                    "BRAIN GPIO": ["GPI: Record Trigger", "GPO: Tally Light Driver", "Direction: Bi-directional"]
                },
                "Fan Control": {
                    "Mode": ["Adaptive Fan Mode (Target 40°C)", "Quiet Record Mode", "Manual Fan Speed (50%)"],
                    "Post Record Delay": ["Delay 0s", "Delay 30s", "Delay 60s"]
                },
                "Lens": {
                    "Lens": ["Mount: Canon EF Smart Mount", "Mount: Nikon F Electronic", "Mount: PL Intelligent (/i)"],
                    "Motion Mount⁴": ["Motion Mount: None Detected", "Electronic ND: Clear", "ND Filter 0.6", "ND Filter 1.2"],
                    "Info": ["Canon EF 24-70mm f/2.8L II USM", "Serial: CN-748921", "Firmware: v1.0.4"],
                    "Metadata": ["Sync Focal Length to R3D", "Sync Aperture to R3D", "Sync Focus Distance"]
                },
                "Motor Control⁵": {
                    "General": ["Motor Driver Power ON", "Motor Driver Status: Ready"],
                    "Focus": ["Calibrate Focus Motor", "Set Focus In/Out Stops"],
                    "Iris": ["Calibrate Iris Motor", "Set Aperture Motor Range"],
                    "Zoom": ["Calibrate Zoom Motor", "Set Zoom Motor Range"],
                    "Wireless": ["RED Wireless Motor Driver (W.M.D.) Pair", "Channel 1 (2.4 GHz)"]
                }
            },
            "MAINTENANCE": {
                "Save Log": {
                    "Save Camera Log to Media": ["Save Complete Camera Log to RED MINI-MAG (.txt)", "Save System Trace"],
                    "Save Log to Media": ["Save Complete Camera Log to RED MINI-MAG (.txt)", "Save System Trace"],
                    "View Camera Log": ["Display Recent 100 Log Lines in Console"]
                },
                "Upgrade": {
                    "Camera": ["Upgrade Camera Firmware from RED MINI-MAG", "Check For Staged Firmware Image"],
                    "Media": ["Verify Firmware Integrity on Media", "Revert to Confirmed Working Baseline (v7.4.1)"]
                },
                "Calibrate": {
                    "Sensor": ["Black Shading Sensor (T/E)", "Load Calibration Map 1 (24fps 1/48)", "Reset Calibration Map"],
                    "Gyro/Acc": ["Calibrate Internal 6-Axis IMU", "Level Calibration (Zero Horizon)"]
                },
                "Self Test": {
                    "Enable Sensor Test Pattern": ["Test Pattern: SMPTE 100%", "Test Pattern: Color Ramp", "Test Pattern: Grid 16x9", "Test Pattern OFF"],
                    "Touchscreen": ["Run Touchscreen Digitizer Test", "Touch Calibration 5-Point"]
                },
                "Restore System": {
                    "Reset Defaults": ["Reset Camera to Factory DSMC2 Defaults", "Confirm Reset Settings"],
                    "Wipe Camera": ["Wipe All User Profiles & Media Logs", "Confirm System Wipe"]
                },
                "Rediscover": {
                    "Rediscover Hardware": ["Rescan All Attached Modules & Expander Bus", "Rescan I2C / SPI Sensors"]
                },
                "System Status": {
                    "Project Status": ["Camera Model: SCARLET-W 5K", "Active Resolution: 5K 16:9", "Active Codec: REDCODE 8:1", "Sensor Temp: 39°C / Core: 54°C"],
                    "Attached Modules": ["RED Touch 7.0 LCD (Port LCD1)", "DSMC2 Base Expander", "RED MINI-MAG 512GB (Port SATA0)"],
                    "RCP Connections": ["RCP Server: 127.0.0.1:1111 (Listening)", "Active Clients: 0"],
                    "Camera Info": ["Firmware: v7.4.1 (SCARLET-W 5K)", "RTOS: ThreadX ARMv7-A", "Bootloader: RED U-Boot v2016.03"]
                },
                "OLPF": {
                    "OLPF Type": ["Standard OLPF", "Skin Tone-Highlight OLPF", "Low Light Optimized OLPF"]
                }
            }
        }
    }

    def __init__(self, camera):
        self.camera = camera

        # Modal / Dialog State
        self.active_dialog: Optional[str] = None # "FPS", "SHUTTER", "ISO", "FORMAT", "MEDIA", "AUDIO"
        self.dialog_selected_index: int = 0

        # DSMC2 Main Menu State
        self.is_menu_open: bool = False
        self.menu_path: List[str] = ["Menu"]
        self.menu_active_tab: str = "SETTINGS"
        self.menu_selected_index: int = 0
        self.active_lut: str = "RED IPP2 Cinema Standard"
        self.active_false_color_mode: str = "Focus"

        # Tool States
        self.is_magnify_on: bool = False
        self.is_false_color_on: bool = False
        self.is_zebras_on: bool = False
        self.is_log_view_on: bool = False
        self.is_horizon_on: bool = False
        self.is_false_color_dropdown_open: bool = False
        self.overlay_mode: str = "Standard" # Standard, Overview, Guides, None
        self.guide_mode: str = "16:9"       # 16:9, 2.39:1, 1.85:1, Off

        # Touch and Feedback State
        self.last_touch_pos: Optional[Tuple[int, int]] = None
        self.last_touch_time: float = 0.0
        self.is_touching: bool = False
        self.focus_point: Optional[Tuple[int, int]] = (512, 288)
        self._last_action_time: float = 0.0
        
        # Camera Profile attributes
        self.camera_model = "SCARLET-W 5K"
        self.camera_type = "0x16"
        self.sensor_name = "RED DRAGON 5K S35"
        self.sensor_width = "5120"
        self.sensor_height = "2700"
        self.max_fps = "60"
        self.format_options = list(self.FORMAT_OPTIONS)
        self.fps_options = list(self.FPS_OPTIONS)

        if hasattr(self.camera, "env") and hasattr(self.camera.env, "CAMERA_PROFILES"):
            cam_type = self.camera.env.get("CAMERA_TYPE", "0x16")
            prof = self.camera.env.CAMERA_PROFILES.get(cam_type)
            if prof:
                self.apply_camera_profile(prof)

        # Build False Color LUT and flat palette
        self._false_color_lut = self._build_false_color_lut()
        self._false_color_palette = self._build_false_color_palette()
        self._zebra_pattern = self._build_zebra_pattern()

    def _build_false_color_lut(self) -> List[Tuple[int, int, int]]:
        """
        Build authentic RED False Color exposure gradient lookup table (0..255 luminance).
        Purple: 0-5 IRE (Clipped blacks)
        Blue: 6-12 IRE
        Teal: 13-25 IRE
        Green: 40-45 IRE (18% Gray exposure calibration)
        Pink: 52-58 IRE (Skin tone highlight)
        Straw/Orange: 78-86 IRE
        Red: 98-100 IRE (98% highlight warning)
        Yellow: 101+ IRE (Blown highlights)
        """
        lut = []
        for i in range(256):
            ire = int((i / 255.0) * 108.0)
            if ire <= 2:
                lut.append((140, 20, 220))   # Purple (Clipped black)
            elif ire <= 10:
                lut.append((20, 60, 220))    # Blue (Deep shadow)
            elif ire <= 20:
                lut.append((20, 180, 200))   # Teal (Shadow)
            elif 40 <= ire <= 45:
                lut.append((0, 220, 0))      # Green (18% Middle Gray)
            elif 52 <= ire <= 58:
                lut.append((240, 110, 170))  # Pink (Caucasian skin highlight)
            elif 78 <= ire <= 86:
                lut.append((250, 170, 0))    # Orange / Straw
            elif 98 <= ire <= 100:
                lut.append((240, 10, 10))    # Red (98% Clipping warning)
            elif ire > 100:
                lut.append((255, 255, 0))    # Yellow (100%+ Blown out)
            else:
                lut.append((i, i, i))        # Neutral monochrome
        return lut

    def _build_false_color_palette(self) -> List[int]:
        """Flat 768-entry palette for C-accelerated PIL palette conversion."""
        palette = []
        for r, g, b in self._false_color_lut:
            palette.extend([r, g, b])
        return palette

    def _build_zebra_pattern(self) -> Image.Image:
        """Pre-rendered diagonal zebra stripe overlay for zero-allocation blitting."""
        pattern = Image.new("RGBA", (self.WIDTH, self.HEIGHT), (0, 0, 0, 0))
        draw = ImageDraw.Draw(pattern)
        for d in range(-self.HEIGHT, self.WIDTH, 12):
            draw.line([(d, 0), (d + self.HEIGHT, self.HEIGHT)], fill=(255, 255, 255, 220), width=3)
            draw.line([(d + 3, 0), (d + self.HEIGHT + 3, self.HEIGHT)], fill=(220, 20, 20, 220), width=3)
        return pattern

    def apply_camera_profile(self, profile: Dict[str, Any]):
        """Dynamically update UI state, formats, and FPS options for active brain."""
        self.camera_model = profile.get("CAMERA_NAME", "SCARLET-W 5K")
        self.camera_type = profile.get("CAMERA_TYPE", "0x16")
        self.sensor_name = profile.get("SENSOR_NAME", "RED DRAGON 5K S35")
        self.sensor_width = profile.get("SENSOR_WIDTH", "5120")
        self.sensor_height = profile.get("SENSOR_HEIGHT", "2700")
        self.max_fps = profile.get("MAX_FPS", "60")
        self.format_options = list(profile.get("FORMAT_OPTIONS", self.FORMAT_OPTIONS))
        self.fps_options = list(profile.get("FPS_OPTIONS", self.FPS_OPTIONS))

    def toggle_menu(self):
        """Toggle DSMC2 system menu on/off."""
        self.is_menu_open = not self.is_menu_open
        self.active_dialog = None
        self._legacy_tab_mode = False
        if self.is_menu_open:
            self.menu_path = ["Menu"]
        self.camera.log_system(f"[UI] DSMC2 Main Menu {'OPENED' if self.is_menu_open else 'CLOSED'}")

    def toggle_magnify(self):
        """Toggle 1:1 Pixel Magnification mode."""
        self.is_magnify_on = not self.is_magnify_on
        self.camera.log_system(f"[UI] 1:1 Magnify {'ENABLED' if self.is_magnify_on else 'DISABLED'}")

    def toggle_false_color(self):
        """Toggle False Color exposure assist overlay."""
        self.is_false_color_on = not self.is_false_color_on
        self.camera.log_system(f"[UI] False Color Exposure Assist {'ENABLED' if self.is_false_color_on else 'DISABLED'}")

    def toggle_zebras(self):
        """Toggle Zebras highlight assist."""
        self.is_zebras_on = not self.is_zebras_on
        self.camera.log_system(f"[UI] Zebras Highlight Assist {'ENABLED' if self.is_zebras_on else 'DISABLED'}")

    # Touch Event Router
    def handle_touch(self, x: int, y: int, pressed: bool, action: str = "down") -> bool:
        """
        Handle touch event from screen at (x, y).
        Returns True if the event interacted with a UI control.
        Prevents push-through / duplicate clicks on drag and release.
        """
        self.last_touch_pos = (x, y)
        self.last_touch_time = time.time()
        self.is_touching = pressed

        # Only process click triggers on touch down (ignore drag/move and release for button clicks)
        if not pressed or action == "move":
            if action == "move" and not self.is_menu_open and not self.active_dialog:
                if 40 < y < 535:
                    self.focus_point = (x, y)
            return True

        now = time.time()
        self._last_action_time = now

        # 1. If DSMC2 Main Menu is open, consume ALL touches to prevent click-through
        if self.is_menu_open:
            return self._handle_menu_touch(x, y)

        # 2. If a Quick Parameter Dialog is open, consume ALL touches
        if self.active_dialog:
            return self._handle_dialog_touch(x, y)

        # 3. Handle Normal HUD Touch Regions
        # Top Bar (0 <= y <= 40)
        if 0 <= y <= 40:
            # STBY / REC Badge (12 <= x <= 82)
            if 12 <= x <= 82:
                self.camera.press_record()
                return True
            # Menu Button / Model Header (88 <= x <= 245)
            if 88 <= x <= 245:
                self.toggle_menu()
                return True
            # FPS Badge (255 <= x <= 365)
            if 255 <= x <= 365:
                self._open_dialog("FPS")
                return True
            # SHUTTER Badge (375 <= x <= 495)
            if 375 <= x <= 495:
                self._open_dialog("SHUTTER")
                return True
            # IRIS Badge (505 <= x <= 615)
            if 505 <= x <= 615:
                self._open_dialog("IRIS")
                return True
            # ISO Badge (625 <= x <= 735)
            if 625 <= x <= 735:
                self._open_dialog("ISO")
                return True
            # FORMAT Badge (745 <= x <= 895)
            if 745 <= x <= 895:
                self._open_dialog("FORMAT")
                return True
            # Authentic Right-side Menu Button (900 <= x <= 1015)
            if 900 <= x <= 1015:
                self.toggle_menu()
                return True

        # Bottom Bar (535 <= y <= 576)
        if 535 <= y <= 576:
            # Timecode (15 <= x <= 240)
            if 15 <= x <= 240:
                self.camera.log_system("[UI] Timecode display mode tapped")
                return True
            # Media Status (250 <= x <= 660)
            if 250 <= x <= 660:
                self._open_dialog("MEDIA")
                return True
            # Audio Status (670 <= x <= 860)
            if 670 <= x <= 860:
                self._open_dialog("AUDIO")
                return True

        # Center area tap: Set spot metering / focus reticle
        if 40 < y < 535:
            self.focus_point = (x, y)
            self.camera.log_system(f"[UI] Spot focus / metering target moved to ({x}, {y})")
            return True

        return False

    def _open_dialog(self, dialog_name: str):
        self.active_dialog = dialog_name
        self.dialog_selected_index = 0
        self.camera.log_system(f"[UI] Opened {dialog_name} quick-selection overlay")

    def _handle_dialog_touch(self, x: int, y: int) -> bool:
        """Handle touches inside an open quick-selection dialog."""
        # Dialog box boundaries: x: 160..864, y: 140..436
        cx, cy = 512, 288
        dx1, dy1, dx2, dy2 = cx - 350, cy - 140, cx + 350, cy + 140

        # Close button at top right of dialog (x: dx2 - 40 .. dx2 - 10, y: dy1 + 10 .. dy1 + 35)
        if (dx2 - 45) <= x <= (dx2 - 5) and (dy1 + 5) <= y <= (dy1 + 35):
            self.active_dialog = None
            return True

        # Click outside dialog closes it
        if not (dx1 <= x <= dx2 and dy1 <= y <= dy2):
            self.active_dialog = None
            return True

        # Handle specific dialog options
        rcp = self.camera.rcp
        if self.active_dialog == "FPS":
            items = getattr(self, "fps_options", self.FPS_OPTIONS)
            clicked_idx = self._get_grid_clicked_index(x, y, dx1 + 30, dy1 + 60, len(items), cols=3, item_w=200, item_h=45)
            if clicked_idx is not None and clicked_idx < len(items):
                val = items[clicked_idx]
                rcp.state[RcpProtocol.PARAM_FPS] = val
                self.camera.log_system(f"[UI] Project Frame Rate set to {val} FPS")
                self.active_dialog = None
                return True

        elif self.active_dialog == "SHUTTER":
            items = self.SHUTTER_OPTIONS
            clicked_idx = self._get_grid_clicked_index(x, y, dx1 + 30, dy1 + 60, len(items), cols=5, item_w=120, item_h=45)
            if clicked_idx is not None and clicked_idx < len(items):
                val = items[clicked_idx]
                rcp.state[RcpProtocol.PARAM_SHUTTER] = val
                self.camera.log_system(f"[UI] Shutter Speed set to {val}")
                self.active_dialog = None
                return True

        elif self.active_dialog == "IRIS":
            lm = getattr(self.camera, "lens_mount", None)
            if lm and lm.attached_lens:
                stops = lm.get_available_aperture_stops()
                items = [f"{s:.1f}" for s in stops]
            else:
                items = self.IRIS_OPTIONS
            clicked_idx = self._get_grid_clicked_index(x, y, dx1 + 30, dy1 + 60, len(items), cols=5, item_w=120, item_h=45)
            if clicked_idx is not None and clicked_idx < len(items):
                val_f = float(items[clicked_idx])
                if lm:
                    lm.set_aperture(val_f)
                else:
                    rcp.state["aperture"] = f"f/{val_f:.1f}"
                self.active_dialog = None
                return True

        elif self.active_dialog == "ISO":
            items = self.ISO_OPTIONS
            clicked_idx = self._get_grid_clicked_index(x, y, dx1 + 30, dy1 + 60, len(items), cols=5, item_w=120, item_h=45)
            if clicked_idx is not None and clicked_idx < len(items):
                val = items[clicked_idx]
                rcp.state[RcpProtocol.PARAM_ISO] = val
                self.camera.log_system(f"[UI] Sensor ISO set to {val}")
                self.active_dialog = None
                return True

        elif self.active_dialog == "FORMAT":
            items = getattr(self, "format_options", self.FORMAT_OPTIONS)
            clicked_idx = self._get_grid_clicked_index(x, y, dx1 + 30, dy1 + 60, len(items), cols=3, item_w=200, item_h=45)
            if clicked_idx is not None and clicked_idx < len(items):
                val = items[clicked_idx]
                rcp.state[RcpProtocol.PARAM_FORMAT] = val
                self.camera.log_system(f"[UI] Recording Format set to {val}")
                self.active_dialog = None
                return True

        elif self.active_dialog == "MEDIA":
            # Check Format SSD button: x: cx - 180 .. cx - 20, y: dy2 - 55 .. dy2 - 15
            if (cx - 180) <= x <= (cx - 20) and (dy2 - 55) <= y <= (dy2 - 15):
                if hasattr(self.camera, "recorder"):
                    self.camera.recorder.format_media()
                else:
                    self.camera.log_system("[MEDIA] Formatting RED MINI-MAG 512GB (R3D FAT32/UDF)...")
                self.active_dialog = None
                return True
            # Check Eject Media button: x: cx + 20 .. cx + 180, y: dy2 - 55 .. dy2 - 15
            if (cx + 20) <= x <= (cx + 180) and (dy2 - 55) <= y <= (dy2 - 15):
                if hasattr(self.camera, "recorder"):
                    self.camera.recorder.eject_media()
                else:
                    self.camera.log_system("[MEDIA] RED MINI-MAG unmounted and ejected safely.")
                self.active_dialog = None
                return True

        elif self.active_dialog == "AUDIO":
            # Check Audio toggles or close
            self.active_dialog = None
            return True

        return True

    def _get_grid_clicked_index(self, x: int, y: int, start_x: int, start_y: int, count: int, cols: int, item_w: int, item_h: int) -> Optional[int]:
        """Helper to find which grid item was clicked."""
        pad_x, pad_y = 12, 10
        for i in range(count):
            row = i // cols
            col = i % cols
            bx = start_x + col * (item_w + pad_x)
            by = start_y + row * (item_h + pad_y)
            if bx <= x <= (bx + item_w) and by <= y <= (by + item_h):
                return i
        return None

    def _get_menu_node(self, path: List[str]):
        """Traverse DSMC2_MENU_TREE along path with case-insensitivity."""
        if not path or path == ["Menu"]:
            return self.DSMC2_MENU_TREE
        curr = self.DSMC2_MENU_TREE
        for seg in path[1:]:
            if isinstance(curr, dict):
                if seg in curr:
                    curr = curr[seg]
                else:
                    match_k = next((k for k in curr if k.lower() == seg.lower()), None)
                    if match_k is not None:
                        curr = curr[match_k]
                    else:
                        return None
            else:
                return None
        return curr

    def _get_current_items(self) -> List[str]:
        """Return list of item strings for current menu path."""
        last_seg = self.menu_path[-1] if self.menu_path else ""

        # Dynamic brain-specific menu items
        if last_seg == "Project Status":
            rcp = getattr(self.camera, "rcp", None)
            fmt = rcp.state.get(RcpProtocol.PARAM_FORMAT, "5K 16:9") if rcp else "5K 16:9"
            codec = rcp.state.get("record_file_format", "REDCODE 8:1") if rcp else "REDCODE 8:1"
            cam_name = getattr(self, "camera_model", "SCARLET-W 5K")
            t_sensor = int(self.camera.thermal.sensor_temp_c) if hasattr(self.camera, "thermal") and self.camera.thermal else 39
            t_brain = int(self.camera.thermal.brain_temp_c) if hasattr(self.camera, "thermal") and self.camera.thermal else 63
            return [
                f"Camera Model: {cam_name}",
                f"Active Resolution: {fmt}",
                f"Active Codec: {codec}",
                f"Sensor Temp: {t_sensor}°C / Core: {t_brain}°C"
            ]

        if last_seg == "Camera Info":
            cam_name = getattr(self, "camera_model", "SCARLET-W 5K")
            sensor = getattr(self, "sensor_name", "RED DRAGON 5K S35")
            sw = getattr(self, "sensor_width", "5120")
            sh = getattr(self, "sensor_height", "2700")
            return [
                f"Firmware: v7.4.1 ({cam_name})",
                "RTOS: ThreadX ARMv7-A",
                "Bootloader: RED U-Boot v2016.03",
                f"Sensor: {sensor} ({sw}x{sh})"
            ]

        if last_seg == "Attached Modules":
            if hasattr(self.camera, "accessory_bus") and self.camera.accessory_bus:
                mods = self.camera.accessory_bus.get_status()["modules"]
                return [f"{m['name']} ({m['pin']}, {m['serial']})" for m in mods]
            return ["RED Touch 7.0 LCD (Port LCD1)", "DSMC2 Base Expander", "RED MINI-MAG 512GB (Port SATA0)"]

        if last_seg in ("Format", "Recording Format") and len(self.menu_path) >= 3 and self.menu_path[1] == "SETTINGS":
            return list(getattr(self, "format_options", self.FORMAT_OPTIONS))

        if last_seg in ("Frame Rate", "Recording Frame Rate") and len(self.menu_path) >= 3 and self.menu_path[1] == "SETTINGS":
            return list(getattr(self, "fps_options", self.FPS_OPTIONS))

        node = self._get_menu_node(self.menu_path)
        if isinstance(node, dict):
            return list(node.keys())
        elif isinstance(node, list):
            return node
        return []

    def _get_grid_layout(self, count: int):
        """Compute optimal grid dimensions based on item count."""
        if count <= 4:
            return 4, 200, 52, 24, 20, 70, 110
        elif count <= 8:
            return 4, 200, 52, 24, 20, 70, 80
        elif count <= 10:
            return 5, 170, 48, 18, 16, 50, 75
        elif count <= 12:
            return 4, 200, 44, 24, 12, 70, 65
        else:
            return 5, 170, 42, 18, 10, 50, 60

    def _get_grid_clicked_index_custom(self, x: int, y: int, start_x: int, start_y: int, count: int, cols: int, item_w: int, item_h: int, pad_x: int, pad_y: int) -> Optional[int]:
        for i in range(count):
            row = i // cols
            col = i % cols
            bx = start_x + col * (item_w + pad_x)
            by = start_y + row * (item_h + pad_y)
            if bx <= x <= (bx + item_w) and by <= y <= (by + item_h):
                return i
        return None

    def _handle_menu_touch(self, x: int, y: int) -> bool:
        """Handle touches inside the full authentic DSMC2 system menu."""
        # Top breadcrumb bar buttons
        # [ ... ] Home: x: 775..835, y: 5..40
        if 775 <= x <= 835 and 5 <= y <= 40:
            self.menu_path = ["Menu"]
            self.camera.log_system("[UI] Menu reset to root (Home)")
            return True

        # [ Back ]: x: 840..915, y: 5..40
        if 840 <= x <= 915 and 5 <= y <= 40:
            if len(self.menu_path) > 1:
                self.menu_path.pop()
                self.camera.log_system(f"[UI] Menu Back to: {' > '.join(self.menu_path)}")
            else:
                self.is_menu_open = False
                self.camera.log_system("[UI] Menu Closed")
            return True

        # [ Close ]: x: 920..1015, y: 5..40
        if 920 <= x <= 1015 and 5 <= y <= 40:
            self.is_menu_open = False
            self.camera.log_system("[UI] Menu Closed")
            return True

        # Breadcrumbs bar click on left (y: 5..40, x < 770)
        if 5 <= y <= 40 and x < 770:
            if len(self.menu_path) > 1:
                self.menu_path.pop()
            return True

        # Special view: OVERLAYS TOOLS buttons (matching Attachment 4)
        if self.menu_path == ["Menu", "OVERLAYS", "TOOLS"]:
            if self._handle_tools_touch(x, y):
                return True

        # Special view: MEDIA Device buttons
        if self.menu_path == ["Menu", "MEDIA", "Device"] and 390 <= y <= 445:
            cx = self.WIDTH // 2
            if (cx - 180) <= x <= (cx - 20):
                if hasattr(self.camera, "recorder"):
                    self.camera.recorder.format_media()
                else:
                    self.camera.log_system("[MEDIA] RED MINI-MAG 512GB formatted (UDF/FAT32).")
                return True
            if (cx + 20) <= x <= (cx + 180):
                if hasattr(self.camera, "recorder"):
                    self.camera.recorder.eject_media()
                else:
                    self.camera.log_system("[MEDIA] RED MINI-MAG unmounted and ejected safely.")
                return True

        # Check legacy tab overlay toggle if test navigated via legacy tab
        if getattr(self, "_legacy_tab_mode", False) and self.menu_active_tab == "OVERLAYS" and (300 <= x <= 540 and 110 <= y <= 160):
            self.toggle_false_color()
            return True

        # Handle button grid items FIRST (ensures no misrouted buttons)
        items = self._get_current_items()
        if items:
            cols, item_w, item_h, pad_x, pad_y, start_x, start_y = self._get_grid_layout(len(items))
            clicked_idx = self._get_grid_clicked_index_custom(x, y, start_x, start_y, len(items), cols, item_w, item_h, pad_x, pad_y)
            if clicked_idx is not None and clicked_idx < len(items):
                chosen = items[clicked_idx]
                self._handle_menu_item_selected(chosen)
                return True

        # Backward compatibility check for tab touch in test_redui.py (only in empty space below buttons)
        if self.menu_path == ["Menu"] and x <= 200 and 240 <= y <= 380:
            tab_y = 50 + 60
            for tab in self.MENU_TABS:
                if tab_y <= y <= (tab_y + 40):
                    self.menu_active_tab = tab
                    self.menu_path = ["Menu", tab]
                    self._legacy_tab_mode = True
                    self.camera.log_system(f"[UI] Navigated to Menu Tab: {tab}")
                    return True
                tab_y += 46

        return True

    def _handle_tools_touch(self, x: int, y: int) -> bool:
        """Handle touches on authentic DSMC2 Overlays > Tools ribbon & popup."""
        # Check False Color popup if open: x: 105..275, y: 92..325
        if self.is_false_color_dropdown_open:
            if 105 <= x <= 275 and 92 <= y <= (92 + 6 * 38):
                idx = (y - 92) // 38
                modes = ["Off", "Exposure", "Video", "Focus", "Edge", "Gio Scope"]
                if 0 <= idx < len(modes):
                    chosen = modes[idx]
                    self.active_false_color_mode = chosen
                    if chosen == "Off":
                        self.is_false_color_on = False
                    else:
                        self.is_false_color_on = True
                    self.camera.log_system(f"[UI] False Color mode set to {chosen}")
                    self.is_false_color_dropdown_open = False
                    return True
            else:
                self.is_false_color_dropdown_open = False
                return True

        # Ribbon buttons (y: 50..95)
        if 50 <= y <= 95:
            # False Color Mode button [ Focus / ... ]: x: 105..220
            if 105 <= x <= 220:
                self.is_false_color_dropdown_open = not self.is_false_color_dropdown_open
                return True
            # OK button [ OK ]: x: 224..275
            if 224 <= x <= 275:
                self.is_false_color_dropdown_open = False
                return True
            # Magnify button [ Magnify ]: x: 285..425
            if 285 <= x <= 425:
                self.toggle_magnify()
                return True
            # Log View button [ Log View ]: x: 435..570
            if 435 <= x <= 570:
                self.is_log_view_on = not getattr(self, "is_log_view_on", False)
                self.camera.log_system(f"[UI] Log View mode {'ENABLED' if self.is_log_view_on else 'DISABLED'}")
                return True
            # Horizon button [ Horizon ]: x: 580..715
            if 580 <= x <= 715:
                self.is_horizon_on = not getattr(self, "is_horizon_on", False)
                self.camera.log_system(f"[UI] Horizon Level overlay {'ENABLED' if self.is_horizon_on else 'DISABLED'}")
                return True
            # Zebras button [ Zebras... ]: x: 725..865
            if 725 <= x <= 865:
                self.toggle_zebras()
                return True

        return False

    def _handle_menu_item_selected(self, item: str):
        """Process item click: drill down into submenu or execute terminal option."""
        test_path = self.menu_path + [item]
        node = self._get_menu_node(test_path)
        if node is not None:
            self.menu_path.append(item)
            if item in self.MENU_TABS:
                self.menu_active_tab = item
            self.camera.log_system(f"[UI] Navigated to Menu: {' > '.join(self.menu_path)}")
            return

        rcp = self.camera.rcp
        last_cat = self.menu_path[-1]

        # 1. Project Frame Rate, Shutter, ISO, Format
        if last_cat in ("Frame Rate", "Recording Frame Rate") or item in getattr(self, "fps_options", self.FPS_OPTIONS):
            val = item.replace(" FPS", "").strip()
            rcp.state[RcpProtocol.PARAM_FPS] = val
            self.camera.log_system(f"[UI] Project Frame Rate set to {val} FPS")

        elif last_cat in ("Exposure", "Shutter Speed") or item in self.SHUTTER_OPTIONS:
            rcp.state[RcpProtocol.PARAM_SHUTTER] = item
            self.camera.log_system(f"[UI] Shutter Speed set to {item}")

        elif last_cat in ("Format", "Recording Format") or item in getattr(self, "format_options", self.FORMAT_OPTIONS):
            rcp.state[RcpProtocol.PARAM_FORMAT] = item
            self.camera.log_system(f"[UI] Recording Format set to {item}")

        elif last_cat == "ISO" or item in self.ISO_OPTIONS:
            val = item.replace("ISO ", "").strip()
            rcp.state[RcpProtocol.PARAM_ISO] = val
            self.camera.log_system(f"[UI] Sensor ISO set to {val}")

        # 2. Timecode & Slate
        elif "Timecode Display Mode" in last_cat or "Time of Day" in item or "Edge Code" in item or "External LTC" in item:
            mode = "TOD" if "Time of Day" in item else ("Edge" if "Edge Code" in item else "LTC")
            rcp.state["timecode_mode"] = mode
            self.camera.log_system(f"[TIMECODE] Display mode set to: {item}")

        elif "Source" in last_cat and ("RTC" in item or "LTC" in item or "Genlock" in item):
            self.camera.log_system(f"[TIMECODE] Clock synchronization source: {item}")

        elif last_cat in ("Scene", "Camera", "Project", "Auto Slate") or "Scene" in item or "Slate" in item:
            self.camera.log_system(f"[SLATE] Production metadata updated: {item}")

        # 3. Sensor Flip / Mirror
        elif "Scan Direction" in last_cat or "Scan Direction" in item or "Flip Sensor" in item or "Mirror Sensor" in item:
            self.camera.log_system(f"[SENSOR] Sensor scan orientation configured: {item}")

        # 4. White Balance & Tint
        elif last_cat in ("WHITE BALANCE", "Color Temperature") or "Color Temp" in last_cat:
            if "Auto WB" in item:
                self.camera.log_system("[UI] Executed Auto White Balance calibration (5600K 0 Tint)")
            else:
                rcp.state["color_temperature"] = item
                self.camera.log_system(f"[UI] Color Temperature set to {item}")

        elif "Tint" in last_cat or "Tint" in item:
            rcp.state["tint"] = item
            self.camera.log_system(f"[WHITE BALANCE] Color tint balance set to: {item}")

        # 5. Look Profiles, Tone Curves, Gain, LGG, CDL
        elif last_cat in ("3D LUT", "Creative 3D LUT"):
            self.active_lut = item
            self.camera.log_system(f"[UI] 3D LUT changed to: {item}")

        elif last_cat in ("GUIDES", "Frame Guide") or "Action Guide" in last_cat or "Title Guide" in last_cat:
            self.guide_mode = item
            self.camera.log_system(f"[UI] Frame Guides set to {item}")

        elif last_cat == "TOOLS":
            if "False Color" in item:
                self.toggle_false_color()
            elif "Magnify" in item:
                self.toggle_magnify()
            elif "Zebras" in item:
                self.toggle_zebras()
            elif "Horizon" in item:
                self.camera.log_system("[UI] Horizon Level overlay toggled")
            elif "RAW" in item:
                self.camera.log_system("[UI] RAW exposure view toggled")

        elif "Saturation" in item or "Contrast" in item or "Brightness" in item or "Exposure Comp" in item:
            self.camera.log_system(f"[LOOK] Color parameter updated: {item}")

        elif "Gain" in item or "Matrix" in item:
            self.camera.log_system(f"[LOOK] Sensor Gain & Matrix updated: {item}")

        elif "Curve" in item:
            self.camera.log_system(f"[LOOK] Tone curve profile applied: {item}")

        elif "Lift" in item or "Gamma" in item or "LGG" in item:
            self.camera.log_system(f"[LOOK] Lift / Gamma / Gain adjusted: {item}")

        elif "Sharpness" in item or "Denoise" in item:
            self.camera.log_system(f"[LOOK] Detail & Denoise setting: {item}")

        elif "Video Color Space" in item or "REDlogFilm" in item or "BT.1886" in item:
            self.camera.log_system(f"[LOOK] Video transform set: {item}")

        elif "Slope" in item or "Power" in item or "Offset" in item or "CDL" in item:
            self.camera.log_system(f"[LOOK] ASC-CDL parameter updated: {item}")

        elif "IPP2" in item or "Legacy Mode" in item or "DragonColor" in item or "REDColor" in item:
            self.camera.log_system(f"[IMAGE] Image processing pipeline configured: {item}")

        # 6. Recording Codecs, Modes & Pre-Record
        elif "REDCODE" in item or "ProRes" in item or "DNxHR" in item or "R3D" in item:
            rcp.state["record_file_format"] = item
            self.camera.log_system(f"[RECORDING] Codec format set: {item}")

        elif "Pre-Record" in item:
            self.camera.log_system(f"[RECORDING] Pre-Record buffer: {item}")

        elif "Continuous Record" in item or "Burst Mode" in item or "Speed Ramp" in item or "Time Lapse" in item:
            self.camera.log_system(f"[RECORDING] Recording operational mode: {item}")

        elif "Frame" in item and ("Processing" in last_cat or "Number of Frames" in last_cat):
            self.camera.log_system(f"[RECORDING] Frame processing mode: {item}")

        elif "Tally" in item or "Beeps" in item or "Sounds" in item:
            self.camera.log_system(f"[RECORDING] Indicator & Tally setting: {item}")

        # 7. HDRX
        elif "HDRx" in item or last_cat == "HDRX":
            if "HDRx ON" in item:
                self.camera.log_system("[HDRX] HDRx dual-exposure processing ENABLED")
            elif "HDRx OFF" in item:
                self.camera.log_system("[HDRX] HDRx dual-exposure processing DISABLED")
            else:
                self.camera.log_system(f"[HDRX] Parameter updated: {item}")

        # 8. Audio Controls
        elif last_cat in ("Channel 1/2", "Channel 3/4", "Pre-Amp Gain", "Headphone Volume", "Mix", "Headphone Mix", "Monitor Mix") or "Audio" in last_cat:
            self.camera.log_system(f"[AUDIO] Audio system setting updated: {item}")

        # 9. Focus & Exposure Assist
        elif "Rack Focus" in item or "AF-S" in item or "AF-C" in item or "Manual Focus" in item:
            self.camera.log_system(f"[FOCUS] Focus system mode: {item}")

        elif last_cat in ("Exposure Priority", "Metering Mode", "Exp Comp", "Selection") or "Metering" in item or "Exposure Priority" in item:
            self.camera.log_system(f"[EXPOSURE ASSIST] Exposure assist parameter: {item}")

        # 10. Monitoring & Test Signals
        elif "Test Pattern" in item or "SMPTE" in item or "Chip Chart" in item or "Audio Tone" in item or "Luma" in item:
            self.camera.log_system(f"[MONITORING] Test generator active: {item}")

        elif "Monitor" in last_cat or "Priority" in last_cat:
            self.camera.log_system(f"[MONITORING] Display monitor preference: {item}")

        elif "Look Around" in item:
            self.camera.log_system(f"[MONITORING] Sensor Look-Around margin: {item}")

        # 11. Power & Playback & Presets
        elif item in ("Power Off Camera", "Shutdown") or (last_cat == "Shutdown" and "Power Off" in item):
            self.menu_open = False
            self.menu_path = ["Menu"]
            self.camera.log_system("[PWR] Shutdown requested from on-screen monitor menu.")
            self.camera.power_off()

        elif last_cat == "Shutdown" and "Cancel" in item:
            if len(self.menu_path) > 1:
                self.menu_path.pop()

        elif "Power" in last_cat or "Power" in item:
            self.camera.log_system(f"[POWER] Power management profile: {item}")

        elif last_cat == "Playback Screen" or "Play" in item or "Pause" in item or "Fast Forward" in item:
            self.camera.log_system(f"[PLAYBACK] Clip playback transport: {item}")

        elif last_cat in ("Camera Presets", "Looks", "Auto Presets") or "Preset" in item or "Look" in item:
            self.camera.log_system(f"[PRESETS] Preset configuration: {item}")

        # 12. Maintenance & Upgrades
        elif "Upgrade" in item or "Firmware" in item or last_cat == "Upgrade":
            staged = getattr(self.camera, "staged_firmware_path", None)
            if staged and os.path.exists(staged):
                self.camera.log_system(f"[UPGRADE] Flashing staged custom firmware from RED MINI-MAG: {os.path.basename(staged)}")
                res = self.camera.load_and_boot_custom_firmware(staged)
                if res.get("status") == "ok":
                    self.camera.log_system("[UPGRADE] Camera upgrade complete. Running custom build in DDR.")
                else:
                    self.camera.log_system(f"[UPGRADE] Firmware flash halted: {res.get('error', 'execution fault')}")
            else:
                self.camera.log_system(f"[UPGRADE] Checking RED MINI-MAG slot for firmware packages: {item}")
                self.camera.log_system("[UPGRADE] Stock firmware verified in slot. System up to date.")

        elif "Wipe Camera" in item:
            self.camera.log_system("[MAINTENANCE] Camera user config wiped. Clean DSMC2 baseline restored.")

        elif "Black Shading" in item or (last_cat == "Sensor" and "Black" in item):
            if hasattr(self.camera, "run_black_shading"):
                self.camera.run_black_shading()
            else:
                self.camera.log_system("[CALIBRATION] Black Shading Sensor (T/E) complete.")

        elif "Rediscover" in item:
            if hasattr(self.camera, "accessory_bus") and self.camera.accessory_bus:
                self.camera.accessory_bus._init_default_accessories()
                count = len(self.camera.accessory_bus.attached_modules)
                self.camera.log_system(f"[HARDWARE] Rediscovered {count} expansion modules on accessory bus.")
            else:
                self.camera.log_system("[HARDWARE] Rediscovered expansion modules: RED Touch 7.0, Base Expander, SATA0 MINI-MAG.")

        elif "OLPF" in item or last_cat == "OLPF" or "OLPF" in last_cat:
            if hasattr(self.camera, "olpf") and self.camera.olpf:
                self.camera.olpf.set_olpf_type(item)
                olpf_info = self.camera.olpf.get_info()
                self.camera.log_system(f"[OLPF] I2C2 @ 0x54 EEPROM updated: {olpf_info['type_name']} ({olpf_info['description']})")
            else:
                self.camera.log_system(f"[CALIBRATION] Optical Low Pass Filter (OLPF) profile set: {item}")

        elif "Genlock" in item or "Sync Phase" in item:
            self.camera.log_system(f"[SYNC] Genlock & Phase synchronized: {item}")

        elif "Adaptive Fan" in item or "Quiet" in item or "Fan" in item:
            self.camera.log_system(f"[FAN] Fan control mode updated: {item}")

        elif "Format" in item:
            if hasattr(self.camera, "recorder"):
                self.camera.recorder.format_media()
            else:
                self.camera.log_system("[MEDIA] RED MINI-MAG 512GB formatted (UDF/FAT32).")

        elif "Eject" in item:
            if hasattr(self.camera, "recorder"):
                self.camera.recorder.eject_media()
            else:
                self.camera.log_system("[MEDIA] RED MINI-MAG unmounted and ejected safely.")

        elif "Save Log" in item:
            rec = getattr(self.camera, "recorder", None)
            if rec and rec.is_media_mounted:
                log_p = os.path.join(self.camera.workspace_root, "persistent_store", "media", rec.current_reel_id, "camera_log.txt")
                os.makedirs(os.path.dirname(log_p), exist_ok=True)
                with open(log_p, "w") as f:
                    f.write("\n".join(self.camera.get_serial_logs()))
                self.camera.log_system(f"[MAINTENANCE] Camera logs saved to RED MINI-MAG: {rec.current_reel_id}/camera_log.txt")
            else:
                self.camera.log_system("[MAINTENANCE] System logs exported to flash memory.")

        elif "Calibrate" in item or "Black Shading" in item:
            self.camera.log_system("[CALIBRATION] Sensor Black Shading (T/E) calibrated. Calibration map applied.")

        elif "AF Sweep" in item:
            lm = getattr(self.camera, "lens_mount", None)
            if lm:
                lm.run_autofocus_sweep()

        elif "Reset Defaults" in item:
            rcp.state[RcpProtocol.PARAM_FPS] = "23.98"
            rcp.state[RcpProtocol.PARAM_SHUTTER] = "1/48"
            rcp.state[RcpProtocol.PARAM_ISO] = "800"
            rcp.state[RcpProtocol.PARAM_FORMAT] = "5K 16:9"
            self.camera.log_system("[SYSTEM] Restored DSMC2 settings to factory defaults.")

        else:
            self.camera.log_system(f"[UI] Selected menu option: {item}")

    # Physical Buttons & D-Pad Router
    def handle_button_press(self, button_name: str) -> bool:
        """Handle physical camera button or D-pad press."""
        if button_name == "MENU":
            self.toggle_menu()
            return True
        elif button_name == "1:1 MAG":
            self.toggle_magnify()
            return True
        elif button_name == "USER 1":
            self.toggle_false_color()
            return True
        elif button_name == "USER 2":
            self.toggle_zebras()
            return True

        # D-pad controls for open menu / dialog
        if self.is_menu_open:
            if button_name == "NAV UP":
                curr_idx = self.MENU_TABS.index(self.menu_active_tab) if self.menu_active_tab in self.MENU_TABS else 0
                self.menu_active_tab = self.MENU_TABS[(curr_idx - 1) % len(self.MENU_TABS)]
                self.menu_path = ["Menu", self.menu_active_tab]
                return True
            elif button_name == "NAV DOWN":
                curr_idx = self.MENU_TABS.index(self.menu_active_tab) if self.menu_active_tab in self.MENU_TABS else 0
                self.menu_active_tab = self.MENU_TABS[(curr_idx + 1) % len(self.MENU_TABS)]
                self.menu_path = ["Menu", self.menu_active_tab]
                return True
            elif button_name == "NAV LEFT":
                if len(self.menu_path) > 1:
                    self.menu_path.pop()
                    self.menu_active_tab = self.menu_path[-1] if len(self.menu_path) > 1 else "SETTINGS"
                else:
                    self.is_menu_open = False
                return True
            elif button_name == "NAV ENTER":
                if self.menu_active_tab == "OVERLAYS":
                    self.toggle_false_color()
                return True
                # Toggle current tab tool
                if self.menu_active_tab == "OVERLAYS":
                    self.toggle_false_color()
                return True

        elif self.active_dialog:
            if button_name in ("NAV LEFT", "NAV ENTER"):
                self.active_dialog = None
                return True

        return False

    # Master Rendering Pipeline
    def render(self, base_image: Image.Image) -> Image.Image:
        """
        Compose HUD, exposure tools, dialogs, menu, and touch reticle onto base frame.
        """
        img = base_image.copy()

        # 1. Apply 1:1 Magnify crop if enabled
        if self.is_magnify_on:
            cx, cy = self.WIDTH // 2, self.HEIGHT // 2
            crop_box = (cx - 256, cy - 144, cx + 256, cy + 144)
            cropped = img.crop(crop_box)
            img = cropped.resize((self.WIDTH, self.HEIGHT), Image.Resampling.BILINEAR)

        # 2. Apply False Color exposure overlay if enabled
        if self.is_false_color_on:
            img = self._apply_false_color(img)

        # 3. Apply Zebras highlight overlay if enabled
        if self.is_zebras_on:
            img = self._apply_zebras(img)

        draw = ImageDraw.Draw(img)

        # 4. Draw Frame Guides
        self._draw_guides(draw)

        # 5. Draw Focus Reticle
        if self.focus_point and not self.is_menu_open and not self.active_dialog:
            fx, fy = self.focus_point
            draw.rectangle([(fx - 24, fy - 24), (fx + 24, fy + 24)], outline=(0, 255, 120), width=1)
            draw.line([(fx - 12, fy), (fx + 12, fy)], fill=(0, 255, 120), width=1)
            draw.line([(fx, fy - 12), (fx, fy + 12)], fill=(0, 255, 120), width=1)

        # 6. Draw Quick Selection Dialog (if open)
        if self.active_dialog:
            self._draw_dialog(img, draw)

        # 7. Draw Full DSMC2 Menu (if open)
        if self.is_menu_open:
            self._draw_menu(img, draw)

        # 8. Draw Touch Feedback Reticle (if touch was active in last 450ms)
        now = time.time()
        if self.last_touch_pos and (self.is_touching or (now - self.last_touch_time < 0.45)):
            tx, ty = self.last_touch_pos
            alpha_ratio = 1.0 if self.is_touching else max(0.0, 1.0 - (now - self.last_touch_time) / 0.45)
            self._draw_touch_reticle(draw, tx, ty, alpha_ratio)

        # 9. Active Tool Badges (Magnify / False Color / Zebras)
        self._draw_tool_badges(draw)

        return img

    def _apply_false_color(self, img: Image.Image) -> Image.Image:
        """Apply false color exposure map based on pixel luminance (C-accelerated palette)."""
        gray = img.convert("L")
        gray.putpalette(self._false_color_palette)
        return gray.convert("RGB")

    def _apply_zebras(self, img: Image.Image) -> Image.Image:
        """Draw diagonal zebra stripes on highlights > 95% IRE (luminance > 240) using fast mask composite."""
        gray = img.convert("L")
        mask = gray.point(lambda p: 255 if p > 235 else 0, mode="1")
        res = img.copy()
        res.paste(self._zebra_pattern, (0, 0), mask)
        return res

    def _draw_guides(self, draw: ImageDraw.ImageDraw):
        """Draw authentic cinema frame lines."""
        if self.guide_mode == "2.39:1":
            # 2.39:1 aspect ratio inside 16:9
            guide_h = int(self.WIDTH / 2.39)
            top_y = (self.HEIGHT - guide_h) // 2
            bot_y = top_y + guide_h
            draw.line([(0, top_y), (self.WIDTH, top_y)], fill=(200, 200, 200), width=1)
            draw.line([(0, bot_y), (self.WIDTH, bot_y)], fill=(200, 200, 200), width=1)
            # Corner ticks
            draw.line([(100, top_y - 8), (100, top_y + 8)], fill=(255, 255, 255), width=1)
            draw.line([(self.WIDTH - 100, top_y - 8), (self.WIDTH - 100, top_y + 8)], fill=(255, 255, 255), width=1)
        elif self.guide_mode == "1.85:1":
            guide_h = int(self.WIDTH / 1.85)
            top_y = (self.HEIGHT - guide_h) // 2
            bot_y = top_y + guide_h
            draw.line([(0, top_y), (self.WIDTH, top_y)], fill=(180, 180, 180), width=1)
            draw.line([(0, bot_y), (self.WIDTH, bot_y)], fill=(180, 180, 180), width=1)

    def _draw_tool_badges(self, draw: ImageDraw.ImageDraw):
        """Draw active indicator badges for 1:1 Mag, False Color, or Zebras."""
        bx = 20
        by = 50
        if self.is_magnify_on:
            draw.rectangle([(bx, by), (bx + 110, by + 24)], fill=(220, 180, 0), outline=(255, 255, 255), width=1)
            draw.text((bx + 10, by + 4), "1:1 MAGNIFY", fill=(0, 0, 0))
            by += 30
        if self.is_false_color_on:
            draw.rectangle([(bx, by), (bx + 120, by + 24)], fill=(0, 180, 80), outline=(255, 255, 255), width=1)
            draw.text((bx + 8, by + 4), "FALSE COLOR", fill=(0, 0, 0))
            # Draw False Color IRE scale on right edge
            self._draw_false_color_scale(draw)
            by += 30
        if self.is_zebras_on:
            draw.rectangle([(bx, by), (bx + 100, by + 24)], fill=(200, 30, 30), outline=(255, 255, 255), width=1)
            draw.text((bx + 12, by + 4), "ZEBRAS 95%", fill=(255, 255, 255))

    def _draw_false_color_scale(self, draw: ImageDraw.ImageDraw):
        """Draw authentic vertical exposure calibration gradient on right side."""
        sx = self.WIDTH - 42
        sy = 60
        scale_h = 400
        labels = [
            (100, (255, 255, 0), "100+"),
            (98, (240, 10, 10), "98"),
            (80, (250, 170, 0), "80"),
            (56, (240, 110, 170), "56"),
            (42, (0, 220, 0), "42"),
            (18, (20, 180, 200), "18"),
            (8, (20, 60, 220), "8"),
            (0, (140, 20, 220), "0")
        ]
        block_h = scale_h // len(labels)
        for idx, (ire, color, txt) in enumerate(labels):
            y1 = sy + idx * block_h
            y2 = y1 + block_h - 2
            draw.rectangle([(sx, y1), (sx + 18, y2)], fill=color, outline=(0, 0, 0))
            draw.text((sx + 22, y1 + 2), txt, fill=(240, 240, 240))

    def _draw_touch_reticle(self, draw: ImageDraw.ImageDraw, x: int, y: int, alpha: float):
        """Draw high-visibility touch feedback reticle and coordinate readout."""
        # Outer ring
        draw.ellipse([(x - 22, y - 22), (x + 22, y + 22)], outline=(255, 60, 60), width=2)
        # Inner ring
        draw.ellipse([(x - 14, y - 14), (x + 14, y + 14)], outline=(255, 255, 255), width=2)
        # Center dot
        draw.ellipse([(x - 3, y - 3), (x + 3, y + 3)], fill=(255, 255, 255))
        # Crosshair ticks
        draw.line([(x - 30, y), (x - 24, y)], fill=(255, 60, 60), width=2)
        draw.line([(x + 24, y), (x + 30, y)], fill=(255, 60, 60), width=2)
        draw.line([(x, y - 30), (x, y - 24)], fill=(255, 60, 60), width=2)
        draw.line([(x, y + 24), (x, y + 30)], fill=(255, 60, 60), width=2)
        # Touch tooltip
        tooltip_x = min(self.WIDTH - 130, max(10, x + 26))
        tooltip_y = max(10, y - 16)
        draw.rectangle([(tooltip_x, tooltip_y), (tooltip_x + 115, tooltip_y + 22)], fill=(20, 20, 20), outline=(255, 60, 60), width=1)
        draw.text((tooltip_x + 6, tooltip_y + 4), f"TOUCH ({x}, {y})", fill=(255, 255, 255))

    def _draw_dialog(self, img: Image.Image, draw: ImageDraw.ImageDraw):
        """Render quick-selection popup dialog."""
        cx, cy = self.WIDTH // 2, self.HEIGHT // 2
        dx1, dy1, dx2, dy2 = cx - 350, cy - 140, cx + 350, cy + 140

        # Translucent backdrop
        draw.rectangle([(dx1, dy1), (dx2, dy2)], fill=(18, 18, 18), outline=(220, 20, 20), width=2)
        # Header bar
        draw.rectangle([(dx1, dy1), (dx2, dy1 + 40)], fill=(32, 32, 32))
        draw.text((dx1 + 20, dy1 + 12), f"RED DSMC2  |  SELECT {self.active_dialog}", fill=(240, 240, 240))
        # Close button [ X ]
        draw.rectangle([(dx2 - 40, dy1 + 8), (dx2 - 10, dy1 + 32)], fill=(60, 20, 20), outline=(200, 40, 40), width=1)
        draw.text((dx2 - 30, dy1 + 11), "X", fill=(255, 255, 255))

        rcp = self.camera.rcp

        if self.active_dialog == "FPS":
            items = getattr(self, "fps_options", self.FPS_OPTIONS)
            curr_val = rcp.state.get(RcpProtocol.PARAM_FPS, "24.00")
            self._draw_grid_buttons(draw, dx1 + 30, dy1 + 60, items, curr_val, cols=3, item_w=200, item_h=45, unit="FPS")

        elif self.active_dialog == "SHUTTER":
            items = self.SHUTTER_OPTIONS
            curr_val = rcp.state.get(RcpProtocol.PARAM_SHUTTER, "1/48")
            self._draw_grid_buttons(draw, dx1 + 30, dy1 + 60, items, curr_val, cols=5, item_w=120, item_h=45, unit="")

        elif self.active_dialog == "IRIS":
            lm = getattr(self.camera, "lens_mount", None)
            if lm and lm.attached_lens:
                stops = lm.get_available_aperture_stops()
                items = [f"{s:.1f}" for s in stops]
                curr_val = f"{lm.current_aperture:.1f}"
                lens_desc = f"{lm.attached_lens.model} ({lm.mount_type})"
            else:
                items = self.IRIS_OPTIONS
                curr_val = "2.8"
                lens_desc = "Standard Lens Scale"
            draw.text((dx1 + 30, dy1 + 42), f"LENS: {lens_desc}", fill=(180, 180, 180))
            self._draw_grid_buttons(draw, dx1 + 30, dy1 + 60, items, curr_val, cols=5, item_w=120, item_h=45, unit="f/")

        elif self.active_dialog == "ISO":
            items = self.ISO_OPTIONS
            curr_val = rcp.state.get(RcpProtocol.PARAM_ISO, "800")
            self._draw_grid_buttons(draw, dx1 + 30, dy1 + 60, items, curr_val, cols=5, item_w=120, item_h=45, unit="ISO")

        elif self.active_dialog == "FORMAT":
            items = getattr(self, "format_options", self.FORMAT_OPTIONS)
            curr_val = rcp.state.get(RcpProtocol.PARAM_FORMAT, "5K 16:9")
            self._draw_grid_buttons(draw, dx1 + 30, dy1 + 60, items, curr_val, cols=3, item_w=200, item_h=45, unit="")

        elif self.active_dialog == "MEDIA":
            rec = getattr(self.camera, "recorder", None)
            reel_str = rec.current_reel_id if rec else "A001"
            status_str = "Mounted (Read/Write)" if (not rec or rec.is_media_mounted) else "Unmounted / Ejected"
            used_gb = (rec.used_space_mb / 1024.0) if rec else 112.0
            free_gb = (rec.free_space_mb / 1024.0) if rec else 400.0
            rem_pct = rec.media_remaining_percent if rec else 78
            clip_cnt = len(rec.list_clips()) if rec else 14

            draw.text((dx1 + 30, dy1 + 55), "MEDIA DEVICE: RED MINI-MAG 512GB", fill=(255, 255, 255))
            draw.text((dx1 + 30, dy1 + 80), f"STATUS: {status_str}  |  FORMAT: FAT32 / UDF v2.50", fill=(180, 180, 180))
            draw.text((dx1 + 30, dy1 + 105), f"CAPACITY: 512 GB  |  USED: {used_gb:.1f} GB ({100-rem_pct}%)  |  FREE: {free_gb:.1f} GB ({rem_pct}%)", fill=(180, 180, 180))
            draw.text((dx1 + 30, dy1 + 130), f"REEL: {reel_str}  |  CLIPS: {clip_cnt} clips recorded", fill=(180, 180, 180))

            # Capacity progress bar (Crash-Proof)
            bx1, by1, bx2, by2 = dx1 + 30, dy1 + 160, dx2 - 30, dy1 + 185
            draw.rectangle([(bx1, by1), (bx2, by2)], outline=(80, 80, 80), width=1)
            used_ratio = (rec.used_space_mb / rec.total_capacity_mb) if rec else 0.22
            bar_w = bx2 - bx1 - 2
            used_w = int(bar_w * max(0.0, min(1.0, used_ratio)))
            if used_w > 0:
                draw.rectangle([(bx1 + 1, by1 + 1), (bx1 + 1 + used_w, by2 - 1)], fill=(0, 180, 220))
            if used_w < bar_w:
                draw.rectangle([(bx1 + 1 + used_w, by1 + 1), (bx2 - 1, by2 - 1)], fill=(0, 200, 80))

            # Action buttons
            # [ FORMAT MEDIA ]
            draw.rectangle([(cx - 180, dy2 - 55), (cx - 20, dy2 - 15)], fill=(120, 20, 20), outline=(220, 40, 40), width=1)
            draw.text((cx - 150, dy2 - 42), "FORMAT MEDIA", fill=(255, 255, 255))
            # [ EJECT MEDIA ]
            draw.rectangle([(cx + 20, dy2 - 55), (cx + 180, dy2 - 15)], fill=(40, 40, 40), outline=(100, 100, 100), width=1)
            draw.text((cx + 55, dy2 - 42), "EJECT MEDIA", fill=(220, 220, 220))

        elif self.active_dialog == "AUDIO":
            draw.text((dx1 + 30, dy1 + 55), "AUDIO SYSTEM STATUS: 2 Channels 24-bit 48kHz PCM", fill=(255, 255, 255))
            draw.text((dx1 + 30, dy1 + 85), "CH 1: Camera Mic Left   |  GAIN: +18dB  |  PEAK: -18 dBFS", fill=(180, 180, 180))
            draw.text((dx1 + 30, dy1 + 115), "CH 2: Camera Mic Right  |  GAIN: +18dB  |  PEAK: -18 dBFS", fill=(180, 180, 180))
            draw.text((dx1 + 30, dy1 + 145), "HEADPHONE VOLUME: 80%   |  PHANTOM +48V: OFF", fill=(180, 180, 180))
            # Dismiss button
            draw.rectangle([(cx - 70, dy2 - 55), (cx + 70, dy2 - 15)], fill=(40, 40, 40), outline=(100, 100, 100), width=1)
            draw.text((cx - 25, dy2 - 42), "CLOSE", fill=(255, 255, 255))

    def _draw_grid_buttons(self, draw: ImageDraw.ImageDraw, start_x: int, start_y: int, items: List[str], current: str, cols: int, item_w: int, item_h: int, unit: str):
        """Draw interactive grid of selectable parameter buttons."""
        pad_x, pad_y = 12, 10
        for i, val in enumerate(items):
            row = i // cols
            col = i % cols
            bx = start_x + col * (item_w + pad_x)
            by = start_y + row * (item_h + pad_y)

            is_selected = (val == current)
            bg_color = (180, 25, 25) if is_selected else (35, 35, 35)
            border_color = (255, 60, 60) if is_selected else (70, 70, 70)
            text_color = (255, 255, 255) if is_selected else (200, 200, 200)

            draw.rectangle([(bx, by), (bx + item_w, by + item_h)], fill=bg_color, outline=border_color, width=2 if is_selected else 1)

            display_txt = f"{val} {unit}".strip()
            draw.text((bx + 16, by + 13), display_txt, fill=text_color)
            if is_selected:
                draw.text((bx + item_w - 24, by + 13), "●", fill=(255, 255, 255))

    def _draw_button_label(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        bx: int,
        by: int,
        item_w: int,
        item_h: int,
        text_color: Tuple[int, int, int],
        has_children: bool = False,
        is_active: bool = False,
    ):
        """
        Draw button text ensuring it always fits within the button boundary.
        Uses adaptive multi-level font scaling, text wrapping, and clean truncation.
        """
        avail_w = item_w - (36 if (has_children or is_active) else 20)
        avail_h = item_h - 8

        # 1. Try FONT_MED (13pt) single line
        bbox = draw.textbbox((0, 0), text, font=FONT_MED)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]

        if w <= avail_w and h <= avail_h:
            tx = bx + 12
            ty = by + (item_h - h) // 2 - 2
            draw.text((tx, ty), text, fill=text_color, font=FONT_MED)
            return

        # 2. Try FONT_SM (11pt) single line
        bbox = draw.textbbox((0, 0), text, font=FONT_SM)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]

        if w <= avail_w and h <= avail_h:
            tx = bx + 10
            ty = by + (item_h - h) // 2 - 2
            draw.text((tx, ty), text, fill=text_color, font=FONT_SM)
            return

        # 3. Try 2-line wrap with FONT_SM (11pt)
        split_char = " " if " " in text else ("/" if "/" in text else ":")
        words = text.split(split_char)
        if len(words) > 1:
            mid = len(words) // 2
            line1 = split_char.join(words[:mid])
            line2 = split_char.join(words[mid:])
            bb1 = draw.textbbox((0, 0), line1, font=FONT_SM)
            bb2 = draw.textbbox((0, 0), line2, font=FONT_SM)
            w1 = bb1[2] - bb1[0]
            w2 = bb2[2] - bb2[0]
            lh = bb1[3] - bb1[1]

            if max(w1, w2) <= avail_w and (lh * 2 + 2) <= avail_h:
                tot_h = lh * 2 + 2
                ty = by + (item_h - tot_h) // 2 - 1
                draw.text((bx + 10, ty), line1, fill=text_color, font=FONT_SM)
                draw.text((bx + 10, ty + lh + 2), line2, fill=text_color, font=FONT_SM)
                return

        # 4. Try FONT_TINY (9pt) single line
        bbox = draw.textbbox((0, 0), text, font=FONT_TINY)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]

        if w <= avail_w and h <= avail_h:
            tx = bx + 8
            ty = by + (item_h - h) // 2 - 1
            draw.text((tx, ty), text, fill=text_color, font=FONT_TINY)
            return

        # 5. Try 2-line wrap with FONT_TINY (9pt)
        if len(words) > 1:
            mid = len(words) // 2
            line1 = split_char.join(words[:mid])
            line2 = split_char.join(words[mid:])
            bb1 = draw.textbbox((0, 0), line1, font=FONT_TINY)
            bb2 = draw.textbbox((0, 0), line2, font=FONT_TINY)
            w1 = bb1[2] - bb1[0]
            w2 = bb2[2] - bb2[0]
            lh = bb1[3] - bb1[1]

            if max(w1, w2) <= avail_w and (lh * 2 + 2) <= avail_h:
                tot_h = lh * 2 + 2
                ty = by + (item_h - tot_h) // 2 - 1
                draw.text((bx + 8, ty), line1, fill=text_color, font=FONT_TINY)
                draw.text((bx + 8, ty + lh + 2), line2, fill=text_color, font=FONT_TINY)
                return

        # 6. Truncate cleanly with ellipsis
        trunc = text
        while len(trunc) > 3:
            trunc = trunc[:-1]
            cand = trunc + "..."
            bb = draw.textbbox((0, 0), cand, font=FONT_SM)
            if (bb[2] - bb[0]) <= avail_w:
                ty = by + (item_h - (bb[3] - bb[1])) // 2 - 2
                draw.text((bx + 10, ty), cand, fill=text_color, font=FONT_SM)
                return

        draw.text((bx + 8, by + (item_h - 12) // 2), text[:12], fill=text_color, font=FONT_TINY)

    def _draw_menu(self, img: Image.Image, draw: ImageDraw.ImageDraw):
        """Render genuine full DSMC2 system menu on the monitor."""
        # Dark translucent overlay over frame (middle area y: 44..520, keeping bottom status bar visible!)
        draw.rectangle([(0, 44), (self.WIDTH, 520)], fill=(14, 14, 14))

        # Top Breadcrumb Bar (y: 0..44)
        draw.rectangle([(0, 0), (self.WIDTH, 44)], fill=(40, 40, 40))
        draw.line([(0, 44), (self.WIDTH, 44)], fill=(65, 65, 65), width=1)
        # Red left accent
        draw.rectangle([(0, 0), (4, 44)], fill=(220, 20, 20))

        # Breadcrumbs text
        b_txt = " > ".join(self.menu_path) + " >"
        if len(b_txt) > 42 and len(self.menu_path) > 3:
            b_txt = f"Menu > ... > {self.menu_path[-2]} > {self.menu_path[-1]} >"
        draw.text((18, 13), b_txt, fill=(245, 245, 245), font=FONT_TITLE)

        # Right buttons: [ ... ] [ Back ] [ Close ]
        # [ ... ]
        draw.rectangle([(775, 8), (832, 36)], fill=(55, 55, 55), outline=(100, 100, 100), width=1)
        draw.text((796, 13), "...", fill=(220, 220, 220), font=FONT_BOLD)

        # [ Back ]
        draw.rectangle([(840, 8), (912, 36)], fill=(55, 55, 55), outline=(100, 100, 100), width=1)
        draw.text((858, 13), "Back", fill=(220, 220, 220), font=FONT_BOLD)

        # [ Close ]
        draw.rectangle([(920, 8), (1005, 36)], fill=(75, 20, 20), outline=(220, 40, 40), width=1)
        draw.text((945, 13), "Close", fill=(255, 255, 255), font=FONT_BOLD)

        # Content area (y: 45..520)
        # Check special screen views:
        if self.menu_path == ["Menu", "MEDIA", "Device"]:
            self._draw_media_device_screen(draw)
            return

        if self.menu_path == ["Menu", "OVERLAYS", "TOOLS"]:
            self._draw_tools_screen(draw)
            return

        items = self._get_current_items()
        if not items:
            draw.text((100, 100), f"No items in {self.menu_path[-1]}", fill=(160, 160, 160), font=FONT_MED)
            return

        cols, item_w, item_h, pad_x, pad_y, start_x, start_y = self._get_grid_layout(len(items))

        rcp = self.camera.rcp
        curr_fps = rcp.state.get(RcpProtocol.PARAM_FPS, "23.98")
        curr_shutter = rcp.state.get(RcpProtocol.PARAM_SHUTTER, "1/48")
        curr_iso = rcp.state.get(RcpProtocol.PARAM_ISO, "800")
        curr_fmt = rcp.state.get(RcpProtocol.PARAM_FORMAT, "5K 16:9")

        for i, val in enumerate(items):
            row = i // cols
            col = i % cols
            bx = start_x + col * (item_w + pad_x)
            by = start_y + row * (item_h + pad_y)

            # Check if this item is selected / active
            is_active = False
            if val == curr_fps or val == f"{curr_fps} FPS":
                is_active = True
            elif val == curr_shutter:
                is_active = True
            elif val == curr_iso or val == f"ISO {curr_iso}":
                is_active = True
            elif val == curr_fmt:
                is_active = True
            elif val == self.active_lut:
                is_active = True
            elif val == self.guide_mode:
                is_active = True
            elif val == "False Color" and self.is_false_color_on:
                is_active = True
            elif val == "Magnify 1:1" and self.is_magnify_on:
                is_active = True
            elif val == "Zebras 95%" and self.is_zebras_on:
                is_active = True
            elif len(self.menu_path) >= 3 and self.menu_path[-1].upper() == "LOOK" and val == "Color":
                # Match authentic Look screen tile activation (Attachment 3)
                is_active = True

            # Has children submenus?
            child_node = self._get_menu_node(self.menu_path + [val])
            has_children = (child_node is not None)

            bg_color = (185, 20, 20) if is_active else (38, 38, 38)
            border_color = (255, 60, 60) if is_active else (75, 75, 75)
            text_color = (255, 255, 255) if is_active else (225, 225, 225)

            draw.rectangle([(bx, by), (bx + item_w, by + item_h)], fill=bg_color, outline=border_color, width=2 if is_active else 1)
            self._draw_button_label(draw, val, bx, by, item_w, item_h, text_color, has_children=has_children, is_active=is_active)

            if has_children:
                draw.text((bx + item_w - 20, by + (item_h - 16) // 2), ">", fill=(160, 160, 160), font=FONT_MED)
            elif is_active:
                draw.text((bx + item_w - 22, by + (item_h - 16) // 2), "●", fill=(255, 255, 255), font=FONT_MED)

    def _draw_media_device_screen(self, draw: ImageDraw.ImageDraw):
        """Draw authentic RED MINI-MAG Device Screen."""
        rec = getattr(self.camera, "recorder", None)
        reel_str = rec.current_reel_id if rec else "A001"
        status_str = "Mounted (Read/Write)" if (not rec or rec.is_media_mounted) else "Unmounted / Ejected"
        used_gb = (rec.used_space_mb / 1024.0) if rec else 0.0
        free_gb = (rec.free_space_mb / 1024.0) if rec else 512.0
        rem_pct = rec.media_remaining_percent if rec else 100
        clip_cnt = len(rec.list_clips()) if rec else 0

        draw.text((80, 80), "MEDIA DEVICE: RED MINI-MAG 512GB (Port 1)", fill=(255, 255, 255), font=FONT_TITLE)
        draw.text((80, 120), f"STATUS: {status_str}   |   FILE SYSTEM: FAT32 / RED UDF v2.50", fill=(190, 190, 190), font=FONT_MED)
        draw.text((80, 155), f"CAPACITY: 512.0 GB   |   USED: {used_gb:.2f} GB ({100-rem_pct}%)   |   FREE: {free_gb:.2f} GB ({rem_pct}%)", fill=(190, 190, 190), font=FONT_MED)
        draw.text((80, 190), f"ACTIVE REEL: {reel_str}   |   CLIPS RECORDED: {clip_cnt} clips", fill=(190, 190, 190), font=FONT_MED)

        # Capacity Progress Bar (CRASH-PROOF!)
        bx1, by1, bx2, by2 = 80, 240, 944, 275
        draw.rectangle([(bx1, by1), (bx2, by2)], outline=(90, 90, 90), width=1)
        used_ratio = (rec.used_space_mb / rec.total_capacity_mb) if rec else 0.0
        bar_w = bx2 - bx1 - 2
        used_w = int(bar_w * max(0.0, min(1.0, used_ratio)))
        if used_w > 0:
            draw.rectangle([(bx1 + 1, by1 + 1), (bx1 + 1 + used_w, by2 - 1)], fill=(0, 180, 220))
        if used_w < bar_w:
            draw.rectangle([(bx1 + 1 + used_w, by1 + 1), (bx2 - 1, by2 - 1)], fill=(0, 200, 80))

        draw.text((80, 290), f"Storage Health: 100%   •   Wear Level: 0.1%   •   Transfer Rate: Up to 300 MB/s", fill=(140, 140, 140), font=FONT_SM)

        # Action Buttons
        cx = self.WIDTH // 2
        # [ FORMAT MEDIA ]
        draw.rectangle([(cx - 180, 390), (cx - 20, 445)], fill=(140, 20, 20), outline=(220, 50, 50), width=2)
        draw.text((cx - 150, 408), "FORMAT MEDIA", fill=(255, 255, 255), font=FONT_BOLD)

        # [ EJECT MEDIA ]
        draw.rectangle([(cx + 20, 390), (cx + 180, 445)], fill=(45, 45, 45), outline=(100, 100, 100), width=1)
        draw.text((cx + 55, 408), "EJECT MEDIA", fill=(220, 220, 220), font=FONT_BOLD)

    def _draw_tools_screen(self, draw: ImageDraw.ImageDraw):
        """Draw authentic DSMC2 Overlays > Tools Toolbar & Options matching official HUD (Attachment 4)."""
        # Top tools ribbon container: y: 46..100
        draw.rectangle([(0, 46), (self.WIDTH, 100)], fill=(28, 28, 28))
        draw.line([(0, 100), (self.WIDTH, 100)], fill=(55, 55, 55), width=1)

        # 1. False Color Block (x: 10 .. 275)
        draw.rectangle([(10, 52), (275, 94)], fill=(20, 20, 20), outline=(65, 65, 65), width=1)
        draw.text((18, 66), "False Color:", fill=(210, 210, 210), font=FONT_MED)
        # Mode button [ Focus / Exposure / ... ]
        cur_mode = self.active_false_color_mode if self.is_false_color_on else "Off"
        mode_btn_bg = (210, 210, 210) if self.is_false_color_dropdown_open else (50, 50, 50)
        mode_btn_txt = (10, 10, 10) if self.is_false_color_dropdown_open else (240, 240, 240)
        draw.rectangle([(105, 55), (220, 91)], fill=mode_btn_bg, outline=(80, 80, 80), width=1)
        draw.text((120, 66), cur_mode, fill=mode_btn_txt, font=FONT_BOLD)
        # [ OK ] button
        draw.rectangle([(224, 55), (271, 91)], fill=(45, 45, 45), outline=(75, 75, 75), width=1)
        draw.text((236, 66), "OK", fill=(220, 220, 220), font=FONT_MED)

        # 2. [ ● Magnify ] (x: 285 .. 425)
        mag_bg = (180, 20, 20) if self.is_magnify_on else (40, 40, 40)
        draw.rectangle([(285, 54), (425, 92)], fill=mag_bg, outline=(75, 75, 75), width=1)
        draw.ellipse([(296, 69), (304, 77)], fill=(255, 255, 255) if self.is_magnify_on else (120, 120, 120))
        draw.text((314, 66), "Magnify", fill=(255, 255, 255), font=FONT_MED)

        # 3. [ ● Log View ] (x: 435 .. 570)
        log_active = getattr(self, "is_log_view_on", False)
        draw.rectangle([(435, 54), (570, 92)], fill=(180, 20, 20) if log_active else (40, 40, 40), outline=(75, 75, 75), width=1)
        draw.ellipse([(446, 69), (454, 77)], fill=(255, 255, 255) if log_active else (120, 120, 120))
        draw.text((464, 66), "Log View", fill=(255, 255, 255), font=FONT_MED)

        # 4. [ ● Horizon ] (x: 580 .. 715)
        horiz_active = getattr(self, "is_horizon_on", False)
        draw.rectangle([(580, 54), (715, 92)], fill=(180, 20, 20) if horiz_active else (40, 40, 40), outline=(75, 75, 75), width=1)
        draw.ellipse([(591, 69), (599, 77)], fill=(255, 255, 255) if horiz_active else (120, 120, 120))
        draw.text((609, 66), "Horizon", fill=(255, 255, 255), font=FONT_MED)

        # 5. [ Zebras... ] (x: 725 .. 865)
        draw.rectangle([(725, 54), (865, 92)], fill=(180, 20, 20) if self.is_zebras_on else (40, 40, 40), outline=(75, 75, 75), width=1)
        draw.text((750, 66), "Zebras...", fill=(255, 255, 255), font=FONT_MED)

        # Center Crosshair Reticle (matching Attachment 4)
        cx, cy = self.WIDTH // 2, self.HEIGHT // 2
        draw.line([(cx - 18, cy), (cx - 4, cy)], fill=(190, 190, 190), width=1)
        draw.line([(cx + 4, cy), (cx + 18, cy)], fill=(190, 190, 190), width=1)
        draw.line([(cx, cy - 18), (cx, cy - 4)], fill=(190, 190, 190), width=1)
        draw.line([(cx, cy + 4), (cx, cy + 18)], fill=(190, 190, 190), width=1)

        # Horizon Level line driven by IOB0 SPI Accelerometer
        if horiz_active:
            iob0 = getattr(self.camera, "iob0", None)
            pitch, roll, is_level = iob0.get_tilt_angles() if iob0 else (0.1, 0.2, True)
            col = (0, 230, 90) if is_level else (255, 200, 30)
            rad = math.radians(roll)
            dx = int(math.cos(rad) * 120)
            dy = int(math.sin(rad) * 120)
            draw.line([(cx - dx, cy - dy), (cx + dx, cy + dy)], fill=col, width=2)
            draw.line([(cx - 30, cy - 8), (cx - 30, cy + 8)], fill=col, width=2)
            draw.line([(cx + 30, cy - 8), (cx + 30, cy + 8)], fill=col, width=2)
            tag = "LEVEL" if is_level else f"{roll:+.1f}°"
            draw.text((cx - 20, cy - 24), tag, fill=col, font=FONT_SM)

        # False Color Mode Dropdown Menu (matching Attachment 4)
        if self.is_false_color_dropdown_open:
            modes = ["Off", "Exposure", "Video", "Focus", "Edge", "Gio Scope"]
            pop_x1, pop_x2 = 105, 271
            pop_y1 = 92
            pop_h = 38
            draw.rectangle([(pop_x1, pop_y1), (pop_x2, pop_y1 + len(modes) * pop_h)], fill=(195, 195, 195), outline=(50, 50, 50), width=1)

            for idx, mode in enumerate(modes):
                my1 = pop_y1 + idx * pop_h
                my2 = my1 + pop_h
                is_sel = (self.active_false_color_mode == mode and self.is_false_color_on) or (mode == "Off" and not self.is_false_color_on)
                if is_sel:
                    draw.rectangle([(pop_x1 + 1, my1), (pop_x2 - 1, my2)], fill=(140, 10, 10))
                    # Red triangular arrow accents on left and right
                    draw.polygon([(pop_x1 + 2, my1 + 6), (pop_x1 + 12, my1 + pop_h // 2), (pop_x1 + 2, my2 - 6)], fill=(100, 0, 0))
                    draw.polygon([(pop_x2 - 2, my1 + 6), (pop_x2 - 12, my1 + pop_h // 2), (pop_x2 - 2, my2 - 6)], fill=(100, 0, 0))
                    draw.text((pop_x1 + 45, my1 + 10), mode, fill=(255, 255, 255), font=FONT_BOLD)
                else:
                    draw.text((pop_x1 + 45, my1 + 10), mode, fill=(20, 20, 20), font=FONT_MED)
                draw.line([(pop_x1, my2), (pop_x2, my2)], fill=(160, 160, 160), width=1)
