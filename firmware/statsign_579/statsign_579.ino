#include <Arduino.h>

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
  Paint_NewImage(ImageBW, EPD_W, EPD_H, Rotation, WHITE);
  Paint_Clear(WHITE);

  EPD_DrawRectangle(0, 0, EPD_W - 1, EPD_H - 1, BLACK, 0);
  EPD_DrawLine(0, 0, EPD_W - 1, EPD_H - 1, BLACK);
  EPD_DrawLine(EPD_W - 1, 0, 0, EPD_H - 1, BLACK);
  EPD_ShowString(20, 20, "STATSIGN", 24, BLACK);

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
