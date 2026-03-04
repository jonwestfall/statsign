#pragma once
#include <Arduino.h>

// Device name shown in BLE scans
static const char* kBleName = "JON_EINK_579";

// Custom service + characteristics (same as we discussed)
static const char* kSvcUUID  = "6a4e0001-6f44-4f7a-a3b2-2f9b3c1c0001";
static const char* kCtrlUUID = "6a4e0002-6f44-4f7a-a3b2-2f9b3c1c0001";
static const char* kDataUUID = "6a4e0003-6f44-4f7a-a3b2-2f9b3c1c0001";
static const char* kProgUUID = "6a4e0004-6f44-4f7a-a3b2-2f9b3c1c0001";

// Expected framebuffer size for 5.79" 272x792 @ 1bpp:
static constexpr int kW = 272;
static constexpr int kH = 792;
static constexpr size_t kFbLen = (size_t)kW * (size_t)kH / 8; // 26928

// ACK pacing
static constexpr size_t kAckEvery = 2048;
