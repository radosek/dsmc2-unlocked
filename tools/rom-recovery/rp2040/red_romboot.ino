// RED DM3725 ROM UART3 boot rig (RP2040).
// Wiring: GP0 -100R- IRLZ44N gate (gate -10k- GND); source GND; drain = NODE = J15 pin29 (H20) + 1k to 3V3 + 1k to GND.
//         GP1 <- J15 pin27 (H21).  3V3 -4k7- AE21 (sys_boot5).  GND common.  GP26 on NODE (ADC probe).
// The FET inverts GP0, so TX is inverted in the UART.
// Default: transparent USB<->UART3 bridge, UART 8E1, for TI pserial on the Mac.
// Host magic (8 bytes, ESC '#' tag '#' ESC LF):  "8N1" -> bridge 8N1 (SPL/u-boot console)   "8E1" -> bridge 8E1
//                                                "RSB" -> auto mode: answers EVERY ASIC ID it sees (8E1, 5 ms after the ID) and logs a timestamped pin29 timeline.
#include "spl_data.h"
#include "hardware/adc.h"

static const uint32_t CMD = 0xF0030002;
static const char MAGIC_8N1[] = "\x1b#8N1#\x1b\n";
static const char MAGIC_8E1[] = "\x1b#8E1#\x1b\n";
static const char MAGIC_SHL[] = "\x1b#SHL#\x1b\n";
static const char MAGIC_B500[] = "\x1b#B500#\x1b\n";
static const char MAGIC_RSB[] = "\x1b#RSB#\x1b\n";
static uint8_t win[8]; static int wn = 0;
static bool sweep = false, shell = false;

static uint32_t baud = 115200;
static void setFmt(uint16_t fmt) {
  Serial1.end();
  Serial1.setInvertTX(true);
  Serial1.begin(baud, fmt);
}

static void feedMagic(uint8_t c) {
  if (wn < 8) win[wn++] = c; else { memmove(win, win + 1, 7); win[7] = c; }
  if (wn < 8) return;
  if (!memcmp(win, MAGIC_8N1, 8)) { shell = false; sweep = false; setFmt(SERIAL_8N1); wn = 0; }
  else if (!memcmp(win, MAGIC_8E1, 8)) { shell = false; sweep = false; setFmt(SERIAL_8E1); wn = 0; }
  else if (!memcmp(win, MAGIC_B500, 8)) { baud = 500000; setFmt(SERIAL_8E1); wn = 0; Serial.println("[RP] UART 500000 8E1"); }
  else if (!memcmp(win, MAGIC_SHL, 8)) { shell = true; sweep = false; wn = 0; Serial.println("[RP] shell passthrough (MAX3232 on GP4/GP5)"); }
  else if (!memcmp(win, MAGIC_RSB, 8)) { shell = false; sweep = true; baud = 115200; setFmt(SERIAL_8E1); wn = 0; Serial.println("[RP] auto mode armed"); }
}

static void sendfc(const uint8_t *p, unsigned n) {   // XON 0x11 / XOFF 0x13 from ROM
  static bool paused = false;
  for (unsigned i = 0; i < n; i++) {
    while (Serial1.available()) { int c = Serial1.read(); if (c == 0x13) paused = true; else if (c == 0x11) paused = false; }
    while (paused) { if (Serial1.available()) { if (Serial1.read() == 0x11) paused = false; } }
    Serial1.write(p[i]);
  }
}

static const uint8_t ASIC_SIG[8] = {0x04, 0x01, 0x05, 0x01, 0x36, 0x30, 0x07, 0x07};
static uint8_t sig[8]; static int sn = 0;
static unsigned long lastAdc = 0; static float lastV = -1; static unsigned asicCount = 1;   // first ASIC ID of a session is #2: F0030002 alone

static float pin29() { uint32_t a = 0; for (int k = 0; k < 16; k++) a += adc_read(); return a / 16 * 3.3 / 4095.0; }

static void autoStep() {
  if (millis() - lastAdc > 100) {            // pin29 timeline: print on change > 0.15 V
    lastAdc = millis(); float v = pin29();
    if (lastV < 0 || fabsf(v - lastV) > 0.15f) { Serial.printf("[t=%lu] pin29=%.2fV\n", millis(), v); lastV = v; }
  }
  while (Serial1.available()) {
    uint8_t c = Serial1.read();
    if (sn < 8) sig[sn++] = c; else { memmove(sig, sig + 1, 7); sig[7] = c; }
    if (sn < 8 || memcmp(sig, ASIC_SIG, 8)) continue;
    sn = 0;
    uint8_t rest[50]; Serial1.readBytes(rest, 50);
    asicCount++;
    delay(5);
    float idle = pin29();
    static unsigned long lastId = 0; unsigned long gap = millis() - lastId; lastId = millis();
    // Debug SPL (early UART3 markers '1'..'8'). Listen 8E1 (ROM format) 1.5 s for markers, then 8N1 8 s for the normal banner.
    Serial.printf("[t=%lu] ASIC ID #%u, pin29 idle %.2fV: sending F0030002 + size %u (debug SPL)\n", millis(), asicCount, idle, SPL_LEN);
    uint32_t hdr[2] = {CMD, SPL_LEN};
    sendfc((uint8_t *)hdr, 8);
    sendfc(SPL, SPL_LEN);
    Serial1.flush();
    Serial.printf("[t=%lu] SPL sent (%u bytes); transparent 8E1 bridge from here (YMODEM / console)\n", millis(), SPL_LEN);
    sweep = false; setFmt(SERIAL_8E1); wn = 0;
    return;
    sn = 0; continue;
  }
}

void setup() {
  Serial.begin(115200);
  Serial1.setFIFOSize(1024);
  Serial2.setTX(4); Serial2.setRX(5); Serial2.begin(115200);   // MAX3232 / DSMC shell
  adc_init(); adc_gpio_init(26); adc_select_input(0);
  setFmt(SERIAL_8E1);
}

void loop() {
  if (shell) {
    int m = Serial.available();
    if (m > 0) {
      uint8_t buf[64]; if (m > 64) m = 64; Serial.readBytes(buf, m); Serial2.write(buf, m);
      for (int i = 0; i < m; i++) { if (wn < 8) win[wn++] = buf[i]; else { memmove(win, win + 1, 7); win[7] = buf[i]; }
        if (wn == 8 && (!memcmp(win, MAGIC_RSB, 8) || !memcmp(win, MAGIC_8N1, 8) || !memcmp(win, MAGIC_8E1, 8))) { shell = false; for (int k = 0; k < 8; k++) feedMagic(win[k]); } }
    }
    m = Serial2.available();
    if (m > 0) { uint8_t buf[64]; if (m > 64) m = 64; Serial2.readBytes(buf, m); Serial.write(buf, m); Serial.flush(); }
    return;
  }
  int n = Serial.available();
  if (n > 0) {
    uint8_t buf[64]; if (n > 64) n = 64; Serial.readBytes(buf, n);
    if (!sweep) Serial1.write(buf, n);
    for (int i = 0; i < n; i++) feedMagic(buf[i]);
  }
  if (sweep) { autoStep(); return; }
  n = Serial1.available();
  if (n > 0) {
    static uint8_t rbuf[512];
    if (n > (int)sizeof rbuf) n = sizeof rbuf;
    Serial1.readBytes(rbuf, n);
    Serial.write(rbuf, n);
    if (Serial1.available() == 0) Serial.flush();     // flush only when the UART side is idle (throughput)
  }
}
