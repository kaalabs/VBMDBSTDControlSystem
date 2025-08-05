# ------------------------------------------------------------
# Waterniveau Bewaking – Ultrasoon + LED & veiligheidsrelais
#
# Dit programma meet het waterniveau in een tank met een ultrasone sensor,
# filtert de metingen (moving average), en schakelt een LED en relais
# afhankelijk van het niveau (met hysteresis om 'jitter' te voorkomen).
# 
# Belangrijk: alle functionele parameters worden bij run-time uit een
# configuratiebestand (config.json in flash) gelezen en live toegepast
# als dit bestand wijzigt. Dit maakt beheer zonder herstart mogelijk.
# 
# Het relais is 'normaal aan' (AAN (veilig) als voldoende water, UIT 
# (onveilig) als tank bijna leeg). De LED geeft status via knipperen.
# 
# Gemaakt voor MicroPython (bv. op RP2040, XAIA RP2350).
# ------------------------------------------------------------

from machine import UART, Pin
import utime
from collections import deque
import ujson

# -------- CONFIGURATIE UIT FLASH (config.json) -----------
def load_config(filename="config.json"):
    """
    Laad configuratieparameters uit een JSON-bestand in het flashgeheugen.
    Als het bestand (of parameters) ontbreken, worden defaults gebruikt.
    """
    defaults = {
        "TANK_HEIGHT_MM": 196,           # Hoogte tank in mm
        "SENSOR_TO_WATER_MIN_MM": 30,    # Sensor dode zone in mm
        "MOVING_AVG_N": 10,              # Filtervenster voor metingen
        "CRITICAL_LEVEL_ON_MM": 150,     # Drempel laag water (ingang)
        "CRITICAL_LEVEL_OFF_MM": 180,    # Drempel laag water (uitgang)
        "BOTTOM_LEVEL_ON_MM": 50,        # Drempel bijna leeg (ingang)
        "BOTTOM_LEVEL_OFF_MM": 70,       # Drempel bijna leeg (uitgang)
        "LED_PIN": 15,                   # GPIO-pin voor status LED
        "RELAY_PIN": 16,                 # GPIO-pin voor relais
        "SLOW_BLINK_MS": 700,            # LED-blinktijd laag water
        "FAST_BLINK_MS": 200,            # LED-blinktijd bijna leeg
        "MEASURE_INTERVAL_MS": 1000      # Interval tussen metingen (ms)
    }
    try:
        with open(filename) as f:
            config = ujson.load(f)
        # Vul ontbrekende waarden aan met defaults
        for k, v in defaults.items():
            if k not in config:
                config[k] = v
        return config
    except Exception as e:
        print("FOUT BIJ LADEN CONFIG, defaults worden gebruikt!", e)
        return defaults

def file_md5(filename):
    """
    Bereken MD5-hash van bestand. Gebruikt om wijzigingen aan config.json
    te detecteren zonder inhoud telkens volledig te hoeven vergelijken.
    """
    try:
        with open(filename, 'rb') as f:
            import uhashlib
            m = uhashlib.md5()
            while True:
                data = f.read(128)
                if not data:
                    break
                m.update(data)
            return m.digest()
    except Exception as e:
        return None

# ------ INITIEEL INLADEN VAN CONFIG EN HARDWAREPINNEN ------
CONFIG_FILE = "config.json"
cfg = load_config(CONFIG_FILE)

# UART en hardware-pin instellingen staan vast (voor veiligheid);

SENSOR_UART_NUM = 0
SENSOR_UART_TX = 0
SENSOR_UART_RX = 1
SENSOR_BAUDRATE = 9600
TRIGGER_CMD = b'\x55'  # Commandobyte voor A02YY sensor

OUTPUT_UART_NUM = 1
OUTPUT_UART_TX = 4
OUTPUT_UART_RX = 5
OUTPUT_BAUDRATE = 115200

LED_PIN   = cfg["LED_PIN"]
RELAY_PIN = cfg["RELAY_PIN"]
MOVING_AVG_N = cfg["MOVING_AVG_N"]  # Lengte van filtervenster (alleen bij start)

# --------- PARAMETERS DIE TIJDENS RUN-TIME AANPASBAAR ZIJN ---------
RUNTIME_KEYS = [
    "TANK_HEIGHT_MM",
    "SENSOR_TO_WATER_MIN_MM",
    "CRITICAL_LEVEL_ON_MM",
    "CRITICAL_LEVEL_OFF_MM",
    "BOTTOM_LEVEL_ON_MM",
    "BOTTOM_LEVEL_OFF_MM",
    "SLOW_BLINK_MS",
    "FAST_BLINK_MS",
    "MEASURE_INTERVAL_MS"
]
# runtime_cfg bevat de actuele, toepasbare instellingen voor alarmgrenzen en blinktijden
runtime_cfg = {k: cfg[k] for k in RUNTIME_KEYS}

def update_runtime_cfg(new_cfg):
    """
    Werk runtime-configuratie bij met nieuwe waardes uit config.json.
    Retourneert een lijst van parameters die daadwerkelijk zijn gewijzigd.
    """
    global runtime_cfg
    changes = []
    for k in RUNTIME_KEYS:
        if k in new_cfg and new_cfg[k] != runtime_cfg[k]:
            runtime_cfg[k] = new_cfg[k]
            changes.append(k)
    return changes

# ------------ HARDWARE INITIALISATIE ------------
sensor_uart = UART(SENSOR_UART_NUM, baudrate=SENSOR_BAUDRATE, tx=SENSOR_UART_TX, rx=SENSOR_UART_RX)
pc_uart = UART(OUTPUT_UART_NUM, baudrate=OUTPUT_BAUDRATE, tx=OUTPUT_UART_TX, rx=OUTPUT_UART_RX)
led = Pin(LED_PIN, Pin.OUT)         # Status-LED (rood of oranje)
relais = Pin(RELAY_PIN, Pin.OUT)    # Relais voor bijv. pompschakeling
samples = deque([], maxlen=MOVING_AVG_N)  # Buffer voor meetwaarden (moving average)

# ----------- STATUSMACHINE-DEFINITIES -----------
class LevelState:
    OK = 0      # Voldoende water, geen LED, relais aan (veilig)
    LOW = 1     # Laag water, LED knippert langzaam, relais aan
    BOTTOM = 2  # Zeer laag, LED knippert snel of blijft aan, relais uit (onveilig)

# -------------- HULPFUNCTIES --------------
def send_output(msg):
    """
    Stuur een status- of foutmelding naar de host-PC via UART1.
    Kan gebruikt worden voor logging/debugging.
    """
    pc_uart.write((msg + '\n').encode())

def read_distance():
    """
    Vraagt een meting aan de ultrasone sensor en leest het antwoord.
    Retourneert de gemeten afstand in mm, of None bij een fout.
    Filtert onmogelijke waardes eruit.
    """
    sensor_uart.write(TRIGGER_CMD)
    t_start = utime.ticks_ms()
    while utime.ticks_diff(utime.ticks_ms(), t_start) < 300:
        if sensor_uart.any() >= 4:
            resp = sensor_uart.read(4)
            # A02YY zendt 0xFF 0xFF <high byte> <low byte>
            if resp and resp[0] == 0xFF and resp[1] == 0xFF:
                distance = (resp[2] << 8) + resp[3]
                min_mm = runtime_cfg["SENSOR_TO_WATER_MIN_MM"]
                max_mm = runtime_cfg["TANK_HEIGHT_MM"]
                if min_mm <= distance <= max_mm:
                    return distance
                else:
                    send_output(f'Onwerkelijke waarde afstand: {distance}mm')
                    return None
    send_output('Sensor timeout')
    return None

def get_filtered_level():
    """
    Berekent het gemiddelde van de meest recente metingen.
    Dit onderdrukt pieken en ruis in de sensorwaarden.
    """
    if not samples:
        return None
    return sum(samples) // len(samples)

def update_alarm_logic(waterlevel, prev_state, led_status):
    """
    De kern van de alarmlogica. Bepaalt aan de hand van het gefilterde waterniveau:
    - Welke status (OK/LOW/BOTTOM) actief is
    - Wat de LED moet doen (aan/uit/knipperen)
    - Welk relais-signaal gewenst is
    Hysteresis voorkomt snel heen-en-weer schakelen rond een drempel.
    Returns:
      nieuwe_status (LevelState),
      nieuwe_led_status (bool),
      nieuwe_blink_interval (int, ms),
      gewenste_relais_status (1=AAN, 0=UIT)
    """
    slow_blink = runtime_cfg["SLOW_BLINK_MS"]
    fast_blink = runtime_cfg["FAST_BLINK_MS"]
    crit_on   = runtime_cfg["CRITICAL_LEVEL_ON_MM"]
    crit_off  = runtime_cfg["CRITICAL_LEVEL_OFF_MM"]
    bot_on    = runtime_cfg["BOTTOM_LEVEL_ON_MM"]
    bot_off   = runtime_cfg["BOTTOM_LEVEL_OFF_MM"]

    if waterlevel is None:
        # Geen actuele data: fail-safe (LED uit, relais aan)
        led.value(0)
        return prev_state, False, slow_blink, 1

    if prev_state == LevelState.OK:
        if waterlevel <= crit_on:
            led.value(0)
            return LevelState.LOW, False, slow_blink, 1
        else:
            led.value(0)
            return LevelState.OK, False, slow_blink, 1
    elif prev_state == LevelState.LOW:
        if waterlevel <= bot_on:
            led.value(0)
            return LevelState.BOTTOM, False, fast_blink, 0
        elif waterlevel >= crit_off:
            led.value(0)
            return LevelState.OK, False, slow_blink, 1
        else:
            led.value(not led_status)
            return LevelState.LOW, not led_status, slow_blink, 1
    elif prev_state == LevelState.BOTTOM:
        if waterlevel > bot_off:
            led.value(0)
            return LevelState.LOW, False, slow_blink, 1
        else:
            led.value(1)
            return LevelState.BOTTOM, True, slow_blink, 0
    else:
        led.value(0)
        return LevelState.OK, False, slow_blink, 1

# -------------- HOOFDLUS --------------
def main():
    """
    De hoofdloop van het programma:
    - Meet periodiek het waterniveau
    - Filtert meetwaarden
    - Werkt status/LED/Relais bij op basis van actuele parameters uit config
    - Detecteert automatisch wijzigingen in config.json (via MD5-hash)
      en past nieuwe waarden live toe op thresholds, blinktijden, etc.
    """
    level_state = LevelState.OK
    led_status = False
    blink_interval = runtime_cfg["SLOW_BLINK_MS"]
    last_blink = utime.ticks_ms()
    last_measure = utime.ticks_ms()
    last_valid_level = None
    error_count = 0
    relais_actief = None  # Houdt bij of relais AAN of UIT was

    # Voor config-wijzigingsdetectie
    CONFIG_CHECK_INTERVAL_MS = 5000    # Hoe vaak config.json checken (ms)
    last_cfg_hash = file_md5(CONFIG_FILE)
    last_cfg_check = utime.ticks_ms()

    while True:
        now = utime.ticks_ms()

        # ---- Config-herlaad: detecteer en verwerk aanpassingen in config.json ----
        if utime.ticks_diff(now, last_cfg_check) >= CONFIG_CHECK_INTERVAL_MS:
            cfg_hash = file_md5(CONFIG_FILE)
            if cfg_hash and cfg_hash != last_cfg_hash:
                try:
                    with open(CONFIG_FILE) as f:
                        new_cfg = ujson.load(f)
                    changes = update_runtime_cfg(new_cfg)
                    if changes:
                        send_output("Config update: " + ", ".join(changes))
                    last_cfg_hash = cfg_hash
                except Exception as e:
                    send_output("Fout bij herladen config: %s" % e)
            last_cfg_check = now

        # ---- Meet waterniveau en filter ----
        if utime.ticks_diff(now, last_measure) >= runtime_cfg["MEASURE_INTERVAL_MS"]:
            d = read_distance()
            last_measure = now
            if d is not None:
                waterlevel = max(0, runtime_cfg["TANK_HEIGHT_MM"] - d)
                samples.append(waterlevel)
                filtered_level = get_filtered_level()
                last_valid_level = filtered_level
                send_output(f'Waterniveau: {filtered_level} mm')
                error_count = 0
            else:
                error_count += 1
                send_output('Sensor fout')
                if error_count >= 5:
                    led.value(1)
                    if relais_actief != 0:
                        relais.value(0)  # Set relay to UNSAFE (OFF)
                        relais_actief = 0
                        send_output('Permanent sensor alarm! (Relais op onveilig)')

        # ---- LED/Relais-logica (kan sneller dan meetinterval) ----
        if utime.ticks_diff(now, last_blink) >= blink_interval:
            level_state, led_status, blink_interval, gewenste_relais = update_alarm_logic(
                last_valid_level, level_state, led_status
            )
            # Schakel het relais alleen als de gewenste status verandert
            if relais_actief != gewenste_relais:
                relais.value(gewenste_relais)
                relais_actief = gewenste_relais
                send_output(f'Relais ingesteld op {"AAN (veilig)" if gewenste_relais else "UIT (onveilig)"}')
            last_blink = now

        utime.sleep_ms(30)  # Korte delay om CPU-belasting te verlagen

# Start het programma
main()
