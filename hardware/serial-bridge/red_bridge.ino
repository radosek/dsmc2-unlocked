// RED CTRL serial bridge  — USB CDC <-> Serial1 (UART0) @ 115200 8N1, raw.
// Waveshare RP2040-Zero: Serial1 TX=GP0, RX=GP1 (board default).
// GP0 -> MAX3232 TTL TXD, GP1 <- MAX3232 TTL RXD.
// Minimal and correct: no control protocol, no inter-byte gap, guarded reads.
void setup() {
  Serial.begin(115200);         // USB CDC (host side)
  Serial1.begin(115200);        // UART0 8N1, default pins GP0/GP1
}
void loop() {
  // host -> camera
  int n = Serial.available();
  while (n-- > 0) {
    int b = Serial.read();
    if (b >= 0) Serial1.write((uint8_t)b);
  }
  // camera -> host
  n = Serial1.available();
  while (n-- > 0) {
    int b = Serial1.read();
    if (b >= 0) Serial.write((uint8_t)b);
  }
}
