#pragma once
#include <Arduino.h>

typedef void (*OnFrameReadyFn)();

void ble_init(OnFrameReadyFn onFrameReady);

// Returns pointer to framebuffer + length; filled when a transfer completes successfully.
uint8_t* ble_framebuffer();
size_t ble_framebuffer_len();

// Optional: for showing progress on serial/debug
size_t ble_bytes_received();
bool ble_is_transferring();
