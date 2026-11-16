# Fridge temperature sensors (T2)

Vaccines, insulin and other cold-chain medicines must stay at **2–8 °C**. The notification service alerts the
branch's and the owner's Telegram when a fridge is out of its range for more than 10 minutes, when it is back in
range, and when a sensor has sent nothing for 30 minutes. The 07:30 digest shows yesterday's minimum and maximum per
fridge.

## Set up

1. **Settings → Features:** turn on *Fridge temperature sensors*.
2. **Settings → Notifications → Fridge temperature sensors → Add sensor:** branch, name ("Fridge A"), range
   (default 2–8 °C). Copy the token: it is shown **once** (*New token* replaces it; the old one stops at once).
3. Make the device post its temperature every 1–5 minutes:

```
POST https://<your server>/api/notifications/v1/sensors/readings
Authorization: Bearer fs_…
Content-Type: application/json

{"temperature_c": 5.4}
```

Answers: `200 {"ok": true, "in_range": true, "state": "ok"}`, `401` unknown or deactivated token, `404` the feature
is off. Extra fields (battery, humidity) are ignored; the server's clock is used. The route is public (no login),
limited per IP; only the token identifies the device. Use https in production: the token travels in the header.

## Cheap Wi-Fi sensors that can do this

The probe goes **inside** the fridge on a thin cable; the Wi-Fi board stays outside (a metal fridge blocks Wi-Fi, and
cold drains batteries). A **DS18B20 waterproof probe** (about 1–2 USD) is accurate to ±0.5 °C, enough for a 2–8 °C
check.

| Device | About | How it posts |
| --- | --- | --- |
| **ESP32 or ESP8266 board + DS18B20 probe, ESPHome** | 5–10 USD | `http_request.post` with `headers:` and a `json:` body (recommended: simplest to make exactly this request) |
| **Shelly Plus / Gen3 relay + Shelly Plus Add-On + DS18B20** | 25–35 USD | a Shelly script calling `HTTP.Request` with method POST, headers and body (the Add-On takes up to 5 DS18B20 probes) |
| **Sonoff TH Origin / TH Elite with a DS18B20 probe, flashed with Tasmota** | 15–25 USD | Tasmota rules / scripting `WebQuery` (GET or POST with a body); check the Tasmota docs of your firmware for the header syntax |

### ESPHome example

```yaml
http_request:
  verify_ssl: true

one_wire:
  - platform: gpio
    pin: GPIO4

sensor:
  - platform: dallas_temp
    id: fridge
    name: "Fridge A"
    update_interval: 60s
    on_value:
      then:
        - http_request.post:
            url: https://pharmacy.example.com/api/notifications/v1/sensors/readings
            headers:
              Authorization: !secret fridge_token   # "Bearer fs_…" in secrets.yaml
              Content-Type: application/json
            body: !lambda |-
              return "{\"temperature_c\": " + to_string(id(fridge).state) + "}";
```

(ESPHome's `json:` mapping only sends strings, so the body is built as text here to send a number.)

### Shelly script example (Gen2 / Gen3 with the Add-On)

```js
let URL = "https://pharmacy.example.com/api/notifications/v1/sensors/readings";
let TOKEN = "fs_…";
Timer.set(60000, true, function () {
  let t = Shelly.getComponentStatus("temperature", 100); // the Add-On's first DS18B20
  if (!t || t.tC === null) return;
  Shelly.call("HTTP.Request", {
    method: "POST", url: URL, body: JSON.stringify({ temperature_c: t.tC }),
    headers: { "Authorization": "Bearer " + TOKEN, "Content-Type": "application/json" },
  });
});
```

## Sources

- [ESPHome HTTP Request](https://esphome.io/components/http_request.html)
- [Shelly Sensor Add-On API](https://shelly-api-docs.shelly.cloud/gen2/Addons/ShellySensorAddon),
  [Shelly HTTP service](https://shelly-api-docs.shelly.cloud/gen2/ComponentsAndServices/HTTP/)
- [Tasmota commands](https://github.com/tasmota/docs/blob/master/docs/Commands.md)
