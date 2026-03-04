#include <Arduino.h>
#include <NimBLEDevice.h>
#include <esp_heap_caps.h>

// TODO: include Elecrow display headers from their 5.79 repo/library.
// The whole point is to keep their init + draw calls intact.
// e.g. initDisplay(); drawBuffer(uint8_t* buf, int w, int h);

static const char* DEV_NAME = "JON_EINK_579";

static const char* SVC_UUID  = "6a4e0001-6f44-4f7a-a3b2-2f9b3c1c0001";
static const char* CTRL_UUID = "6a4e0002-6f44-4f7a-a3b2-2f9b3c1c0001";
static const char* DATA_UUID = "6a4e0003-6f44-4f7a-a3b2-2f9b3c1c0001";
static const char* PROG_UUID = "6a4e0004-6f44-4f7a-a3b2-2f9b3c1c0001";

static NimBLECharacteristic* progChr = nullptr;

static uint8_t* fb = nullptr;
static size_t fbLen = 0;
static size_t fbOff = 0;
static uint32_t expectedCrc = 0;
static int imgW = 0, imgH = 0;
static bool inTransfer = false;

static uint32_t crc32(const uint8_t* data, size_t len) {
  // Arduino doesn't provide zlib; use ESP ROM crc32 if desired.
  // For MVP, use esp_rom_crc32_le:
  return esp_rom_crc32_le(0, data, len);
}

static void notifyMsg(const String& s) {
  if (!progChr) return;
  progChr->setValue(s.c_str());
  progChr->notify();
}

static void resetTransfer() {
  if (fb) {
    heap_caps_free(fb);
    fb = nullptr;
  }
  fbLen = fbOff = 0;
  expectedCrc = 0;
  imgW = imgH = 0;
  inTransfer = false;
}

class CtrlCallbacks : public NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic* chr) override {
    std::string v = chr->getValue();
    String cmd = String(v.c_str());
    cmd.trim();

    if (cmd.startsWith("BEGIN ")) {
      resetTransfer();
      // BEGIN w h len crc
      int w, h;
      unsigned int len;
      char crcHex[16] = {0};

      int n = sscanf(cmd.c_str(), "BEGIN %d %d %u %8s", &w, &h, &len, crcHex);
      if (n < 4) { notifyMsg("ERR BEGIN\n"); return; }

      imgW = w; imgH = h; fbLen = (size_t)len;
      expectedCrc = (uint32_t)strtoul(crcHex, nullptr, 16);

      fb = (uint8_t*)heap_caps_malloc(fbLen, MALLOC_CAP_SPIRAM);
      if (!fb) {
        // fallback internal
        fb = (uint8_t*)heap_caps_malloc(fbLen, MALLOC_CAP_8BIT);
      }
      if (!fb) { notifyMsg("ERR NOMEM\n"); resetTransfer(); return; }

      fbOff = 0;
      inTransfer = true;
      notifyMsg("READY\n");
      return;
    }

    if (cmd == "ABORT") {
      resetTransfer();
      notifyMsg("ABORTED\n");
      return;
    }

    if (cmd == "END") {
      if (!inTransfer || !fb || fbOff != fbLen) {
        notifyMsg("ERR LEN\n");
        resetTransfer();
        return;
      }

      uint32_t got = crc32(fb, fbLen);
      if (got != expectedCrc) {
        notifyMsg("CRCFAIL\n");
        resetTransfer();
        return;
      }
      notifyMsg("CRCOK\n");
      notifyMsg("DRAWING\n");

      // TODO: call Elecrow draw routine for 5.79 panel using fb as 1bpp buffer.
      // drawBuffer(fb, imgW, imgH);

      notifyMsg("DONE\n");
      resetTransfer();
      return;
    }
  }
};

class DataCallbacks : public NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic* chr) override {
    if (!inTransfer || !fb) return;
    std::string v = chr->getValue();
    const uint8_t* p = (const uint8_t*)v.data();
    size_t n = v.size();

    size_t remaining = fbLen - fbOff;
    if (n > remaining) n = remaining;
    memcpy(fb + fbOff, p, n);
    fbOff += n;

    // Backpressure: ACK every 2048 bytes
    if ((fbOff % 2048) < n || fbOff == fbLen) {
      notifyMsg("ACK " + String((unsigned int)fbOff) + "\n");
    }
  }
};

void setup() {
  Serial.begin(115200);
  delay(200);

  // TODO: init Elecrow display here (from their examples). :contentReference[oaicite:6]{index=6}

  NimBLEDevice::init(DEV_NAME);
  NimBLEServer* server = NimBLEDevice::createServer();

  NimBLEService* svc = server->createService(SVC_UUID);

  NimBLECharacteristic* ctrl = svc->createCharacteristic(
    CTRL_UUID,
    NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::NOTIFY
  );
  progChr = svc->createCharacteristic(
    PROG_UUID,
    NIMBLE_PROPERTY::NOTIFY
  );
  NimBLECharacteristic* data = svc->createCharacteristic(
    DATA_UUID,
    NIMBLE_PROPERTY::WRITE
  );

  ctrl->setCallbacks(new CtrlCallbacks());
  data->setCallbacks(new DataCallbacks());

  svc->start();

  NimBLEAdvertising* adv = NimBLEDevice::getAdvertising();
  adv->addServiceUUID(SVC_UUID);
  adv->start();

  Serial.println("BLE ready.");
}

void loop() {
  delay(1000);
}
