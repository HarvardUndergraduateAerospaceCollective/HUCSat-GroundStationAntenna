# Imports
import socket
import subprocess
import time
from skyfield.api import load, wgs84


# Config
OBSERVER_LAT = 42.3770
OBSERVER_LON = -71.1167
OBSERVER_ELEV_M = 10
ROTCTLD_HOST = "100.103.23.51"
ROTCTLD_PORT = 4533
UPDATE_INTERVAL = 2

# Rotator hardware config (per HUCSat docs)
# Model: 601=az+el, 609=az only, 610=el only
ROTCTLD_MODEL = 601
ROTCTLD_SERIAL_PORT = "/dev/ttyACM0"
ROTCTLD_BAUD = 9600


# Load TLE + satellite
ts = load.timescale()
cat_nr = 57448  # replace with ACS-3 NORAD ID
url = f"https://celestrak.org/NORAD/elements/gp.php?CATNR={cat_nr}&FORMAT=TLE"
sat = load.tle_file(url)[0]
observer = wgs84.latlon(OBSERVER_LAT, OBSERVER_LON, elevation_m=OBSERVER_ELEV_M)


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
