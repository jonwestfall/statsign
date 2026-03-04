#include <Arduino.h>
#include <string.h>

#include "EPD.h"
#include "ble_sign.h"
#include "pic_home.h"
#include "sign_protocol.h"

uint8_t ImageBW[kFbLen];

static volatile bool gFrameReady = false;
static uint32_t gSuccessfulDraws = 0;

void onFrameReady() {
  gFrameReady = true;
}

static void panelClearAndSleep() {
  EPD_GPIOInit();
  EPD_FastMode1Init();
  EPD_Display_Clear();
  EPD_Update();
  EPD_DeepSleep();
}

static void doCleanRefreshIfNeeded() {
  if ((gSuccessfulDraws % kCleanRefreshEvery) == 0) {
    // Library doesn't expose an explicit global/slow refresh API for this path,
    // so we use clear + full update as our "clean refresh".
    panelClearAndSleep();
  }
}

static void drawDemoPattern() {
  // Build demo directly in the native row-major 1bpp framebuffer format.
  // This avoids dependency on paint text/font paths and guarantees visible pixels.
  memset(ImageBW, 0xFF, kFbLen);

  auto setBlack = [](int x, int y) {
    if (x < 0 || x >= kW || y < 0 || y >= kH) return;
    size_t idx = static_cast<size_t>(y) * static_cast<size_t>(kW / 8) + static_cast<size_t>(x / 8);
    uint8_t bit = static_cast<uint8_t>(7 - (x & 0x7));
    ImageBW[idx] &= static_cast<uint8_t>(~(1U << bit));
  };

  // Border
  for (int x = 0; x < kW; ++x) {
    setBlack(x, 0);
    setBlack(x, kH - 1);
  }
  for (int y = 0; y < kH; ++y) {
    setBlack(0, y);
    setBlack(kW - 1, y);
  }

  // Diagonal lines
  for (int x = 0; x < kW; ++x) {
    int y0 = (x * kH) / kW;
    int y1 = (kH - 1) - y0;
    setBlack(x, y0);
    setBlack(x, y1);
  }

  // A few horizontal bars to make the pattern obvious
  for (int y = 32; y < 40; ++y) {
    for (int x = 32; x < kW - 32; ++x) setBlack(x, y);
  }
  for (int y = kH - 40; y < kH - 32; ++y) {
    for (int x = 32; x < kW - 32; ++x) setBlack(x, y);
  }

  EPD_GPIOInit();
  EPD_FastMode1Init();
  EPD_Display(ImageBW);
  EPD_FastUpdate();
  EPD_DeepSleep();
}

void setup() {
  Serial.begin(115200);

  pinMode(7, OUTPUT);
  digitalWrite(7, HIGH);

  EPD_GPIOInit();
  Paint_NewImage(ImageBW, EPD_W, EPD_H, Rotation, WHITE);
  Paint_Clear(WHITE);
  EPD_FastMode1Init();
  EPD_Display_Clear();
  EPD_Update();

  ble_init(onFrameReady);

  EPD_GPIOInit();
  EPD_FastMode1Init();
  EPD_ShowPicture(0, 0, 792, 272, gImage_home, WHITE);
  EPD_Display(ImageBW);
  EPD_FastUpdate();
  EPD_DeepSleep();

  Serial.printf("Display ready EPD_W=%d EPD_H=%d fb=%u\n",
                EPD_W, EPD_H, static_cast<unsigned>(kFbLen));
}

void loop() {
  ble_poll();

  BleOp op = ble_take_operation();
  if (op == BleOp::Clear) {
    panelClearAndSleep();
  } else if (op == BleOp::Demo) {
    drawDemoPattern();
  }

  if (gFrameReady) {
    gFrameReady = false;

    uint8_t* fb = ble_framebuffer();
    size_t len = ble_framebuffer_len();

    if (fb && len == kFbLen) {
      EPD_GPIOInit();
      EPD_FastMode1Init();
      EPD_Display(fb);
      EPD_FastUpdate();
      EPD_DeepSleep();

      gSuccessfulDraws++;
      doCleanRefreshIfNeeded();
    }
  }

  delay(20);
}
