# Imports
import socket
import subprocess
import time
import urllib.request
from skyfield.api import EarthSatellite, load, wgs84


# Config
OBSERVER_LAT = 42.3631
OBSERVER_LON = -71.1260
OBSERVER_ELEV_M = 10
ROTCTLD_HOST = "100.103.23.51"
ROTCTLD_PORT = 4533
UPDATE_INTERVAL = 2
TLE_REFRESH_HOURS = 6

# Rotator hardware config (per HUCSat docs)
# Model: 601=az+el, 609=az only, 610=el only
ROTCTLD_MODEL = 601
ROTCTLD_SERIAL_PORT = "/dev/ttyACM0"
ROTCTLD_BAUD = 9600


# Load TLE + satellite
ts = load.timescale()
cat_nr = 53494  # norad id


def fetch_sat(catnr):
    url = f"https://celestrak.org/NORAD/elements/gp.php?CATNR={catnr}&FORMAT=TLE"
    req = urllib.request.Request(url, headers={"User-Agent": "HUCSat-GroundStation/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        text = resp.read().decode("utf-8")
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    if len(lines) < 3 or not lines[1].startswith("1 ") or not lines[2].startswith("2 "):
        raise RuntimeError(f"Bad TLE response for CATNR={catnr}: {text!r}")
    s = EarthSatellite(lines[1], lines[2], lines[0], ts)
    if s.model.satnum != catnr:
        raise RuntimeError(f"Celestrak returned satnum {s.model.satnum}, expected {catnr}")
    return s


sat = fetch_sat(cat_nr)
observer = wgs84.latlon(OBSERVER_LAT, OBSERVER_LON, elevation_m=OBSERVER_ELEV_M)

# --- Diagnostics ---
t_now = ts.now()
last_tle_refresh = t_now
epoch_age_days = t_now.tt - sat.epoch.tt
print(f"Tracking: {sat.name} (satnum {sat.model.satnum})")
print(f"TLE epoch age: {epoch_age_days:.1f} days{'  WARNING: stale, positions unreliable!' if epoch_age_days > 3 else ''}")

# Ground track sanity check: LEO alt should be ~400-2000 km; garbage = stale/wrong TLE
geocentric = sat.at(t_now)
if geocentric.message:
    print(f"TLE propagation error: {geocentric.message}")
else:
    subpoint = wgs84.subpoint_of(geocentric)
    print(f"Satellite ground track: lat={subpoint.latitude.degrees:.2f}°  "
          f"lon={subpoint.longitude.degrees:.2f}°  "
          f"alt={subpoint.elevation.km:.0f} km")

# Next passes over observer in 24 hours
t1 = ts.tt_jd(t_now.tt + 1)
times, events = sat.find_events(observer, t_now, t1, altitude_degrees=0.0)
event_names = ["rise", "culminate", "set"]
if len(times) == 0:
    print("No passes in next 24 hours.")
else:
    print("Upcoming passes (UTC):")
    for ti, ev in zip(times, events):
        print(f"  {event_names[ev]:10s} {ti.utc_strftime('%Y-%m-%d %H:%M:%S')}")


# Hamlib send command
# P <azimuth> <elevation>
def send_rotator(az, el):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((ROTCTLD_HOST, ROTCTLD_PORT))
            cmd = f"P {az:.2f} {el:.2f}\n"
            s.sendall(cmd.encode("utf-8"))
    except Exception as e:
        print("Hamlib send error:", e)


# Grant serial port access and start rotctld server
subprocess.run(["sudo", "chmod", "666", ROTCTLD_SERIAL_PORT], check=True)
rotctld_proc = subprocess.Popen([
    "rotctld",
    "-m", str(ROTCTLD_MODEL),
    "-r", ROTCTLD_SERIAL_PORT,
    "-s", str(ROTCTLD_BAUD),
    "-t", str(ROTCTLD_PORT),
])
print(f"rotctld started (PID {rotctld_proc.pid}), waiting for it to be ready...")

# Wait for rotctld to be ready before tracking
while True:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(2)
            s.connect((ROTCTLD_HOST, ROTCTLD_PORT))
        print("rotctld connected.")
        break
    except Exception:
        time.sleep(2)


# Main loop
try:
    while True:
        t = ts.now()
        if (t.tt - last_tle_refresh.tt) * 24 > TLE_REFRESH_HOURS:
            try:
                sat = fetch_sat(cat_nr)
                last_tle_refresh = t
                print(f"TLE refreshed: {sat.name} (satnum {sat.model.satnum})")
            except Exception as e:
                print("TLE refresh failed, using previous TLE:", e)
        difference = sat - observer
        topocentric = difference.at(t)
        alt, az, distance = topocentric.altaz()
        az_deg = az.degrees
        el_deg = alt.degrees
        print(f"AZ: {az_deg:.2f}  EL: {el_deg:.2f}")
        # Only track when above horizon
        if el_deg > 0:
            send_rotator(az_deg, el_deg)
        else:
            print("Satellite below horizon")
        time.sleep(UPDATE_INTERVAL)
finally:
    rotctld_proc.terminate()
    print("rotctld stopped.")
