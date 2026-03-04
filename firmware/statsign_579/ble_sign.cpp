#include "ble_sign.h"
#include "sign_protocol.h"

#include <NimBLEDevice.h>
#include <esp_heap_caps.h>
#include <esp_rom_crc.h>

static NimBLECharacteristic* gProg = nullptr;
static OnFrameReadyFn gOnFrameReady = nullptr;

enum class TransferState : uint8_t {
  IDLE = 0,
  RECEIVING,
  READY_TO_DRAW,
};

static uint8_t* gFb = nullptr;
static size_t gFbLen = kFbLen;
static size_t gOff = 0;
static uint32_t gExpectedCrc = 0;
static uint32_t gComputedCrc = 0;
static TransferState gState = TransferState::IDLE;
static uint32_t gLastDataMs = 0;
static BleOp gPendingOp = BleOp::None;

class ServerCallbacks : public NimBLEServerCallbacks {
  void onDisconnect(NimBLEServer* /*server*/, NimBLEConnInfo& /*connInfo*/, int /*reason*/) override {
    NimBLEDevice::startAdvertising();
    Serial.println("BLE client disconnected; advertising restarted.");
  }
};

static const char* stateName(TransferState s) {
  switch (s) {
    case TransferState::IDLE: return "IDLE";
    case TransferState::RECEIVING: return "RECEIVING";
    case TransferState::READY_TO_DRAW: return "READY_TO_DRAW";
    default: return "UNKNOWN";
  }
}

static void notifyMsg(const String& s) {
  if (!gProg) return;
  gProg->setValue(s.c_str());
  gProg->notify();
}

static void resetTransfer() {
  gOff = 0;
  gExpectedCrc = 0;
  gComputedCrc = 0;
  gLastDataMs = 0;
  gState = TransferState::IDLE;
}

static uint32_t crc32_le(const uint8_t* data, size_t len) {
  return esp_rom_crc32_le(0, data, len);
}

uint8_t* ble_framebuffer() { return gFb; }
size_t ble_framebuffer_len() { return gFbLen; }
size_t ble_bytes_received() { return gOff; }
bool ble_is_transferring() { return gState == TransferState::RECEIVING; }

BleOp ble_take_operation() {
  BleOp op = gPendingOp;
  gPendingOp = BleOp::None;
  return op;
}

void ble_poll() {
  if (gState == TransferState::RECEIVING && gLastDataMs > 0) {
    uint32_t elapsed = millis() - gLastDataMs;
    if (elapsed > kTransferTimeoutMs) {
      notifyMsg("ERR TIMEOUT\n");
      Serial.printf("Transfer timeout in state=%s after %lu ms, off=%u/%u\n",
                    stateName(gState),
                    static_cast<unsigned long>(elapsed),
                    static_cast<unsigned>(gOff),
                    static_cast<unsigned>(gFbLen));
      resetTransfer();
    }
  }
}

class CtrlCallbacks : public NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic* chr, NimBLEConnInfo& /*connInfo*/) override {
    std::string v = chr->getValue();
    String cmd(v.c_str());
    cmd.trim();

    if (cmd.startsWith("BEGIN ")) {
      int w = 0;
      int h = 0;
      unsigned int len = 0;
      unsigned int crc = 0;
      int n = sscanf(cmd.c_str(), "BEGIN %d %d %u %x", &w, &h, &len, &crc);
      if (n != 4) {
        notifyMsg("ERR BEGIN\n");
        return;
      }

      Serial.printf("BEGIN parsed w=%d h=%d len=%u crc=%08x state=%s\n",
                    w, h, len, crc, stateName(gState));

      if (w != kW || h != kH || static_cast<size_t>(len) != kFbLen) {
        notifyMsg("ERR SIZE\n");
        return;
      }

      if (!gFb) {
        gFb = static_cast<uint8_t*>(heap_caps_malloc(gFbLen, MALLOC_CAP_SPIRAM));
        if (!gFb) gFb = static_cast<uint8_t*>(heap_caps_malloc(gFbLen, MALLOC_CAP_8BIT));
        if (!gFb) {
          notifyMsg("ERR NOMEM\n");
          return;
        }
      }

      // Policy: if BEGIN arrives during an in-flight transfer, abort and restart.
      if (gState == TransferState::RECEIVING) {
        notifyMsg("ERR ABORT_RESTART\n");
      }

      resetTransfer();
      gExpectedCrc = crc;
      gState = TransferState::RECEIVING;
      gLastDataMs = millis();
      notifyMsg("READY\n");
      return;
    }

    if (cmd == "ABORT") {
      resetTransfer();
      notifyMsg("ABORTED\n");
      return;
    }

    if (cmd == "INFO") {
      notifyMsg("INFO w=" + String(kW) + " h=" + String(kH) + " len=" +
                String(static_cast<unsigned>(kFbLen)) + " ver=" + kVersion + "\n");
      return;
    }

    if (cmd == "CLEAR") {
      gPendingOp = BleOp::Clear;
      notifyMsg("CLEARING\n");
      return;
    }

    if (cmd == "DEMO") {
      gPendingOp = BleOp::Demo;
      notifyMsg("DEMOING\n");
      return;
    }

    if (cmd == "END") {
      if (gState != TransferState::RECEIVING || !gFb) {
        notifyMsg("ERR STATE\n");
        notifyMsg("DONE\n");
        resetTransfer();
        return;
      }
      if (gOff != gFbLen) {
        notifyMsg("ERR LEN\n");
        notifyMsg("DONE\n");
        resetTransfer();
        return;
      }

      gComputedCrc = crc32_le(gFb, gFbLen);
      bool crcOk = (gComputedCrc == gExpectedCrc);

      Serial.printf("END expected=%08x got=%08x draw=%s\n",
                    static_cast<unsigned>(gExpectedCrc),
                    static_cast<unsigned>(gComputedCrc),
                    crcOk ? "yes" : "no");

      if (!crcOk) {
        notifyMsg("CRCFAIL expected=" + String(gExpectedCrc, HEX) +
                  " got=" + String(gComputedCrc, HEX) + "\n");
        notifyMsg("DONE\n");
        resetTransfer();
        return;
      }

      notifyMsg("CRCOK\n");
      notifyMsg("DRAWING\n");
      notifyMsg("DONE\n");
      gState = TransferState::READY_TO_DRAW;
      if (gOnFrameReady) gOnFrameReady();
      return;
    }

    notifyMsg("ERR CMD\n");
  }
};

class DataCallbacks : public NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic* chr, NimBLEConnInfo& /*connInfo*/) override {
    if (gState != TransferState::RECEIVING || !gFb) {
      notifyMsg("ERR STATE\n");
      return;
    }

    std::string v = chr->getValue();
    const uint8_t* p = reinterpret_cast<const uint8_t*>(v.data());
    size_t n = v.size();
    if (n == 0) return;

    size_t remaining = gFbLen - gOff;
    if (n > remaining) n = remaining;

    memcpy(gFb + gOff, p, n);
    size_t before = gOff;
    gOff += n;
    gLastDataMs = millis();

    if (((before / kAckEvery) != (gOff / kAckEvery)) || gOff == gFbLen) {
      notifyMsg("ACK " + String(static_cast<unsigned>(gOff)) + "\n");
    }
  }
};

void ble_init(OnFrameReadyFn onFrameReady) {
  gOnFrameReady = onFrameReady;

  NimBLEDevice::init(kBleName);
  NimBLEServer* server = NimBLEDevice::createServer();
  server->setCallbacks(new ServerCallbacks());

  NimBLEService* svc = server->createService(kSvcUUID);

  NimBLECharacteristic* ctrl = svc->createCharacteristic(
      kCtrlUUID, NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::NOTIFY);
  NimBLECharacteristic* data = svc->createCharacteristic(
      kDataUUID, NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_NR);

  gProg = svc->createCharacteristic(kProgUUID, NIMBLE_PROPERTY::NOTIFY);

  ctrl->setCallbacks(new CtrlCallbacks());
  data->setCallbacks(new DataCallbacks());

  svc->start();

  NimBLEAdvertising* adv = NimBLEDevice::getAdvertising();
  adv->setName(kBleName);
  adv->addServiceUUID(kSvcUUID);
  adv->start();

  Serial.printf("Boot: ble_name=%s ver=%s geometry=%dx%d len=%u\n",
                kBleName, kVersion, kW, kH, static_cast<unsigned>(kFbLen));
  Serial.println("BLE advertising started.");
}
