#include "ble_sign.h"
#include "sign_protocol.h"

#include <NimBLEDevice.h>
#include <esp_rom_crc.h>
#include <esp_heap_caps.h>

static NimBLECharacteristic* gProg = nullptr;
static OnFrameReadyFn gOnFrameReady = nullptr;

static uint8_t* gFb = nullptr;
static size_t gFbLen = 0;
static size_t gOff = 0;
static uint32_t gExpectedCrc = 0;
static bool gTransferring = false;

class ServerCallbacks : public NimBLEServerCallbacks {
  void onDisconnect(NimBLEServer* /*server*/, NimBLEConnInfo& /*connInfo*/, int /*reason*/) override {
    NimBLEDevice::startAdvertising();
    Serial.println("BLE client disconnected; advertising restarted.");
  }
};

static void notifyMsg(const String& s) {
  if (!gProg) return;
  gProg->setValue(s.c_str());
  gProg->notify();
}

static void resetTransfer() {
  gOff = 0;
  gExpectedCrc = 0;
  gTransferring = false;
}

static uint32_t crc32_le(const uint8_t* data, size_t len) {
  return esp_rom_crc32_le(0, data, len);
}

uint8_t* ble_framebuffer() { return gFb; }
size_t ble_framebuffer_len() { return gFbLen; }
size_t ble_bytes_received() { return gOff; }
bool ble_is_transferring() { return gTransferring; }

class CtrlCallbacks : public NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic* chr, NimBLEConnInfo& /*connInfo*/) override {
    std::string v = chr->getValue();
    String cmd(v.c_str());
    cmd.trim();

    if (cmd.startsWith("BEGIN ")) {
      // BEGIN w h len crc
      int w = 0, h = 0;
unsigned int len = 0;
unsigned int crc = 0;

int n = sscanf(cmd.c_str(), "BEGIN %d %d %u %x", &w, &h, &len, &crc);
if (n < 4) {
  notifyMsg("ERR BEGIN\n");
  Serial.printf("BEGIN parse fail: '%s'\n", cmd.c_str());
  return;
}

Serial.printf("BEGIN w=%d h=%d len=%u crc=%08x\n", w, h, len, crc);
gExpectedCrc = (uint32_t)crc;
      gTransferring = true;
      notifyMsg("READY\n");
      return;
    }

    if (cmd == "ABORT") {
      resetTransfer();
      notifyMsg("ABORTED\n");
      return;
    }

    if (cmd == "END") {
      if (!gTransferring || !gFb || gOff != gFbLen) {
        notifyMsg("ERR LEN\n");
        resetTransfer();
        return;
      }

      uint32_t got = crc32_le(gFb, gFbLen);
      if (got != gExpectedCrc) {
        Serial.printf("CRC expected=%08x got=%08x len=%u\n",
        (unsigned)gExpectedCrc, (unsigned)got, (unsigned)gFbLen);
        notifyMsg("CRCFAIL " + String(got, HEX) + "\n");
        notifyMsg("DONE\n");          // terminal signal, even on failure
        resetTransfer();
      return;
      }

      notifyMsg("CRCOK\n");
      notifyMsg("DONE\n");            // terminal signal
      gTransferring = false;

      if (gOnFrameReady) gOnFrameReady();
      return;

    }
  }
};

class DataCallbacks : public NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic* chr, NimBLEConnInfo& /*connInfo*/) override {
    
    if (!gTransferring || !gFb) return;

    std::string v = chr->getValue();
    const uint8_t* p = (const uint8_t*)v.data();
    size_t n = v.size();

    size_t remaining = gFbLen - gOff;
    if (n > remaining) n = remaining;

    memcpy(gFb + gOff, p, n);
    size_t before = gOff;
    gOff += n;
    Serial.printf("DATA chunk received: %u bytes, total=%u/%u\n",
              (unsigned)v.size(), (unsigned)gOff, (unsigned)gFbLen);
    // ACK every kAckEvery bytes (or on completion)
    if (((before / kAckEvery) != (gOff / kAckEvery)) || gOff == gFbLen) {
      notifyMsg("ACK " + String((unsigned int)gOff) + "\n");
    }
  }
};

void ble_init(OnFrameReadyFn onFrameReady) {
  gOnFrameReady = onFrameReady;

  NimBLEDevice::init(kBleName);
  NimBLEDevice::setMTU(247);
  NimBLEServer* server = NimBLEDevice::createServer();
  server->setCallbacks(new ServerCallbacks());

  NimBLEService* svc = server->createService(kSvcUUID);

  NimBLECharacteristic* ctrl = svc->createCharacteristic(
    kCtrlUUID, NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::NOTIFY
  );
  NimBLECharacteristic* data = svc->createCharacteristic(
    kDataUUID, NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_NR
  );

  gProg = svc->createCharacteristic(
    kProgUUID, NIMBLE_PROPERTY::NOTIFY
  );

  ctrl->setCallbacks(new CtrlCallbacks());
  data->setCallbacks(new DataCallbacks());

  svc->start();

  NimBLEAdvertising* adv = NimBLEDevice::getAdvertising();
  adv->setName(kBleName);
  adv->addServiceUUID(kSvcUUID);
  adv->start();

  Serial.printf("BLE advertising started as '%s'.\n", kBleName);
}
