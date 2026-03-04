#include "EPD.h"

#include <string.h>

PAINT Paint = {0};

static inline uint16_t widthBytes(uint16_t widthPx) {
  return (uint16_t)((widthPx + 7U) / 8U);
}

void Paint_NewImage(uint8_t *image, uint16_t Width, uint16_t Height, uint16_t Rotate, uint16_t Color) {
  Paint.Image = image;
  Paint.width = Width;
  Paint.height = Height;
  Paint.widthMemory = Width;
  Paint.heightMemory = Height;
  Paint.color = Color;
  Paint.rotate = Rotate;
  Paint.widthByte = widthBytes(Width);
  Paint.heightByte = Height;
}

void Paint_SetPixel(uint16_t Xpoint, uint16_t Ypoint, uint16_t Color) {
  if (!Paint.Image) return;
  if (Xpoint >= Paint.widthMemory || Ypoint >= Paint.heightMemory) return;

  uint32_t addr = (uint32_t)Xpoint / 8U + (uint32_t)Ypoint * Paint.widthByte;
  uint8_t mask = (uint8_t)(0x80U >> (Xpoint % 8U));

  if (Color == BLACK) {
    Paint.Image[addr] &= (uint8_t)~mask;
  } else {
    Paint.Image[addr] |= mask;
  }
}

void Paint_Clear(uint8_t Color) {
  if (!Paint.Image) return;
  memset(Paint.Image, Color, (size_t)Paint.widthByte * Paint.heightMemory);
}

void EPD_ShowPicture(uint16_t x, uint16_t y, uint16_t sizex, uint16_t sizey, const uint8_t BMP[], uint16_t /*Color*/) {
  if (!Paint.Image || !BMP) return;

  const uint16_t bytesPerRow = widthBytes(sizex);
  for (uint16_t row = 0; row < sizey; row++) {
    if ((y + row) >= Paint.heightMemory) break;

    uint32_t dst = ((uint32_t)(y + row) * Paint.widthByte) + (x / 8U);
    uint32_t src = (uint32_t)row * bytesPerRow;

    if (dst + bytesPerRow > (uint32_t)Paint.widthByte * Paint.heightMemory) break;
    memcpy(Paint.Image + dst, BMP + src, bytesPerRow);
  }
}

void EPD_DrawLine(uint16_t, uint16_t, uint16_t, uint16_t, uint16_t) {}
void EPD_DrawRectangle(uint16_t, uint16_t, uint16_t, uint16_t, uint16_t, uint8_t) {}
void EPD_DrawCircle(uint16_t, uint16_t, uint16_t, uint16_t, uint8_t) {}
void EPD_ShowChar(uint16_t, uint16_t, uint16_t, uint16_t, uint16_t) {}
void EPD_ShowString(uint16_t, uint16_t, const char *, uint16_t, uint16_t) {}
void EPD_ShowNum(uint16_t, uint16_t, uint32_t, uint16_t, uint16_t, uint16_t) {}
void EPD_ClearWindows(uint16_t, uint16_t, uint16_t, uint16_t, uint16_t) {}
void EPD_ShowFloatNum1(uint16_t, uint16_t, float, uint8_t, uint8_t, uint8_t, uint8_t) {}
void EPD_ShowWatch(uint16_t, uint16_t, float, uint8_t, uint8_t, uint8_t, uint8_t) {}
