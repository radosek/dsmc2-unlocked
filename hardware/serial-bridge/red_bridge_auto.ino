// RED CTRL serial bridge — AUTO line-coding follow (8N1 shell + 8E1 ROM boot, one build).
// Waveshare RP2040-Zero. USB CDC (host) <-> Serial1/UART0 (GP0 TX, GP1 RX) -> MAX3232 -> CTRL LEMO.
//
// WHY: the DSMC2 app shell is 115200 8N1; the DM3725 ROM UART3 peripheral boot is 115200 8E1
// (pserial.c:221 s_configure(115200, EVENPARITY, ONE_STOP_BIT, 8); TRM Rev R 26.4.5).
// This bridge mirrors whatever line coding the host opens onto the camera side, so:
//   - dsh.py / terminal open 8N1 -> camera side 8N1 (shell, u-boot console)
//   - pserial opens 8E1          -> camera side 8E1 (ROM ASIC-ID + SPL download)
// No reflash, no in-band escape (binary-safe for the SPL image).
//
// REQUIRES Tools > USB Stack = "Adafruit TinyUSB" (weak tud_cdc_line_coding_cb hook).
//
// GP2 = sys_boot5 strap drive. Held HIGH => sys_boot[4:0]=0x35 = UART3-first, NAND fallback
// (non-destructive; cold power-cycle required for the ROM to honor it). Strap net is the
// camera 1.8V domain via the owner's 4.7k; GP2 3V3 through the series 4.7k sits ~1.65V on
// the net (over ~1.17V VIH). Set STRAP_DRIVE 0 to leave GP2 as input (no strap, 8N1-only use).

#include <Adafruit_TinyUSB.h>

#define STRAP_PIN   2
#define STRAP_DRIVE 1   // 1 = drive sys_boot5 high (ROM-boot ready); 0 = leave floating/input

// Pending line-coding applied from loop() (callback runs in USB context — don't touch UART there).
static volatile bool     g_pending = false;
static volatile uint32_t g_baud    = 115200;
static volatile uint8_t  g_parity  = 0;   // 0 none, 1 odd, 2 even, 3 mark, 4 space
static volatile uint8_t  g_stop    = 0;   // 0 = 1 stop, 1 = 1.5, 2 = 2 stop
static volatile uint8_t  g_data    = 8;   // 5..8

static uint32_t cur_baud = 0;
static uint16_t cur_cfg  = 0xFFFF;

// Build an arduino-pico SerialUART config word from CDC line-coding fields.
static uint16_t makeConfig(uint8_t data, uint8_t parity, uint8_t stop) {
  uint16_t d, p, s;
  switch (data) { case 5: d = SERIAL_DATA_5; break; case 6: d = SERIAL_DATA_6; break;
                  case 7: d = SERIAL_DATA_7; break; default: d = SERIAL_DATA_8; break; }
  switch (parity) { case 1: p = SERIAL_PARITY_ODD;  break; case 2: p = SERIAL_PARITY_EVEN; break;
                    default: p = SERIAL_PARITY_NONE; break; }   // mark/space -> none (ROM uses none/even only)
  s = (stop == 2) ? SERIAL_STOP_BIT_2 : SERIAL_STOP_BIT_1;      // 1.5 -> 1
  return d | p | s;
}

extern "C" void tud_cdc_line_coding_cb(uint8_t itf, cdc_line_coding_t const* p) {
  (void)itf;
  g_baud   = p->bit_rate;
  g_stop   = p->stop_bits;
  g_parity = p->parity;
  g_data   = p->data_bits;
  g_pending = true;
}

static void applyIfPending() {
  if (!g_pending) return;
  g_pending = false;
  uint32_t baud = g_baud ? g_baud : 115200;
  uint16_t cfg  = makeConfig(g_data, g_parity, g_stop);
  if (baud == cur_baud && cfg == cur_cfg) return;
  Serial1.end();
  Serial1.begin(baud, cfg);
  cur_baud = baud; cur_cfg = cfg;
}

void setup() {
#if STRAP_DRIVE
  pinMode(STRAP_PIN, OUTPUT);
  digitalWrite(STRAP_PIN, HIGH);   // sys_boot5 = 1 (UART3-first). Needs cold power-cycle to take.
#endif
  Serial.begin(115200);            // USB CDC
  Serial1.setTX(0); Serial1.setRX(1);
  Serial1.begin(115200, SERIAL_8N1);
  cur_baud = 115200; cur_cfg = SERIAL_8N1;
}

void loop() {
  applyIfPending();
  int n = Serial.available();
  while (n-- > 0) { int b = Serial.read(); if (b >= 0) Serial1.write((uint8_t)b); }
  n = Serial1.available();
  while (n-- > 0) { int b = Serial1.read(); if (b >= 0) Serial.write((uint8_t)b); }
}
