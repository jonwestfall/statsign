#include <Arduino.h>
#include "EPD.h"
#include "pic_home.h"

#include "ble_sign.h"
#include "sign_protocol.h"

uint8_t ImageBW[27200];

static volatile bool gFrameReady = false;

void onFrameReady() {
  gFrameReady = true;
}

static void renderFrameHighQuality(const uint8_t* frame) {
  if (!frame) return;

  // Use a full refresh waveform for maximum fill quality.
  // Fast/partial waveforms are quicker but can leave under-driven pixels.
  EPD_GPIOInit();
  EPD_Init();
  EPD_Display(frame);
  EPD_Update();
  EPD_DeepSleep();
}

void setup() {
  Serial.begin(115200);

  pinMode(7, OUTPUT);
  digitalWrite(7, HIGH);

  Paint_NewImage(ImageBW, EPD_W, EPD_H, Rotation, WHITE);
  Paint_Clear(WHITE);

  // Start BLE receiver
  ble_init(onFrameReady);

  // Show the home image once at boot using high-quality full refresh mode.
  EPD_ShowPicture(0, 0, 792, 272, gImage_home, WHITE);
  renderFrameHighQuality(ImageBW);
}

void loop() {
  if (gFrameReady) {
    gFrameReady = false;

    uint8_t* fb = ble_framebuffer();
    size_t len = ble_framebuffer_len();

    if (fb && len == kFbLen) {
      renderFrameHighQuality(fb);
    }
  }

  delay(20);
}

void clear_all() {
  EPD_GPIOInit();
  EPD_Init();
  EPD_Display_Clear();
  EPD_Update();
}
