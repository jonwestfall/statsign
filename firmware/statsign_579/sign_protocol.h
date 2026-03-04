#pragma once

#include <Arduino.h>

// Device and BLE protocol identity
static constexpr const char* kVersion = "0.2.0";
static constexpr const char* kBleName = "JON_EINK_579";

// BLE UUIDs (must stay compatible with existing tooling)
static constexpr const char* kSvcUUID = "6a4e0001-6f44-4f7a-a3b2-2f9b3c1c0001";
static constexpr const char* kCtrlUUID = "6a4e0002-6f44-4f7a-a3b2-2f9b3c1c0001";
static constexpr const char* kDataUUID = "6a4e0003-6f44-4f7a-a3b2-2f9b3c1c0001";
static constexpr const char* kProgUUID = "6a4e0004-6f44-4f7a-a3b2-2f9b3c1c0001";

// Locked geometry for Elecrow 5.79" panel driver
static constexpr int kW = 800;
static constexpr int kH = 272;
static constexpr size_t kFbLen = static_cast<size_t>(kW) * static_cast<size_t>(kH) / 8; // 27200

// Transfer behavior
static constexpr size_t kAckEvery = 2048;
static constexpr uint32_t kTransferTimeoutMs = 15000;

// Display refresh policy
static constexpr uint32_t kCleanRefreshEvery = 10;
