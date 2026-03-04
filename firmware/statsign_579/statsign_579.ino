#include <Arduino.h>
#include "EPD.h"
#include "pic_home.h"

#include "ble_sign.h"
#include "sign_protocol.h"

uint8_t ImageBW[27200]; // <-- you won't use this for BLE frames, but keep it for now if you want

static volatile bool gFrameReady = false;

void onFrameReady() {
  gFrameReady = true;
}

void setup() {
  Serial.begin(115200);

  pinMode(7, OUTPUT);
  digitalWrite(7, HIGH);

  // Display init (keep as your working baseline)
  EPD_GPIOInit();
  Paint_NewImage(ImageBW, EPD_W, EPD_H, Rotation, WHITE);
  Paint_Clear(WHITE);

  EPD_FastMode1Init();
  EPD_Display_Clear();
  EPD_Update();

  // Start BLE receiver
  ble_init(onFrameReady);

  // Optional: show the home image once at boot, so you know it’s alive
  EPD_GPIOInit();
  EPD_FastMode1Init();
  EPD_ShowPicture(0, 0, 792, 272, gImage_home, WHITE);
  EPD_Display(ImageBW);
  EPD_FastUpdate();
  EPD_DeepSleep();
}

void loop() {
  if (gFrameReady) {
    gFrameReady = false;

    uint8_t* fb = ble_framebuffer();
    size_t len = ble_framebuffer_len();

    if (fb && len == kFbLen) {
      // Wake + draw using the known-good update sequence
      EPD_GPIOInit();
      EPD_FastMode1Init();

      // IMPORTANT: We need to confirm whether EPD_Display expects:
      // - a packed 1bpp buffer matching your laptop’s packing, and
      // - whether bits are inverted.
      //
      // For MVP: try direct first.
      EPD_Display(fb);
      EPD_FastUpdate();
      EPD_DeepSleep();
    }
  }

  delay(20);
}

void clear_all() {
  EPD_FastMode1Init();
  EPD_Display_Clear();
  EPD_Update();
}