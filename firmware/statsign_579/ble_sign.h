#pragma once

#include <Arduino.h>

enum class BleOp : uint8_t {
  None = 0,
  Clear,
  Demo,
};

typedef void (*OnFrameReadyFn)();

void ble_init(OnFrameReadyFn onFrameReady);
void ble_poll();

uint8_t* ble_framebuffer();
size_t ble_framebuffer_len();
size_t ble_bytes_received();
bool ble_is_transferring();

// Returns a pending operational command and clears it.
BleOp ble_take_operation();
