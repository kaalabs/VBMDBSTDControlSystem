### **Toelichting per parameter in config.json (documentatieblok, niet in JSON plaatsen):**

| Parameter                | Betekenis                                                         | Typische waarde(s) |
| ------------------------ | ----------------------------------------------------------------- | ------------------ |
| `TANK_HEIGHT_MM`         | Hoogte van de tank, in mm. Bepalend voor niveau-berekening.       | 196                |
| `SENSOR_TO_WATER_MIN_MM` | Dode zone van de ultrasoonsensor (onder deze afstand geen meting) | 30                 |
| `MOVING_AVG_N`           | Aantal metingen voor het moving average-filter.                   | 10                 |
| `CRITICAL_LEVEL_ON_MM`   | Drempel (mm boven bodem) waaronder status “LOW” actief wordt.     | 150                |
| `CRITICAL_LEVEL_OFF_MM`  | Drempel waarboven status “LOW” weer uitgaat.                      | 180                |
| `BOTTOM_LEVEL_ON_MM`     | Drempel waaronder status “BOTTOM” (bijna leeg) actief wordt.      | 50                 |
| `BOTTOM_LEVEL_OFF_MM`    | Drempel waarboven status “BOTTOM” weer uitgaat.                   | 70                 |
| `LED_PIN`                | GPIO-pin voor status LED (RP2040/2350-pin-nummer).                | 15                 |
| `RELAY_PIN`              | GPIO-pin voor relais (RP2040/2350-pin-nummer).                    | 16                 |
| `SLOW_BLINK_MS`          | Knippersnelheid LED in “LOW”-status (ms per cyclus).              | 700                |
| `FAST_BLINK_MS`          | Knippersnelheid LED in “BOTTOM”-status (ms per cyclus).           | 200                |
| `MEASURE_INTERVAL_MS`    | Interval tussen nieuwe metingen van de sensor (ms).               | 1000               |


#### **Uitleg Hysteresis:**

* De **ON**-waarden zijn de drempels waarbij een *lagere* status wordt geactiveerd als het water zakt.
* De **OFF**-waarden zijn de drempels waarbij een *hogere* status weer actief wordt als het water stijgt.
* Dit voorkomt snel heen-en-weer schakelen ("jitter") bij schommelingen rond een kritieke waarde.


### **Aandachtspunten bij aanpassen:**

* Zorg dat `CRITICAL_LEVEL_OFF_MM` altijd *hoger* is dan `CRITICAL_LEVEL_ON_MM`.
* Zorg dat `BOTTOM_LEVEL_OFF_MM` altijd *hoger* is dan `BOTTOM_LEVEL_ON_MM`.
* De pin-nummers zijn afhankelijk van je hardware/bord.
* Het moving average (`MOVING_AVG_N`) werkt alleen bij herstart, niet live.