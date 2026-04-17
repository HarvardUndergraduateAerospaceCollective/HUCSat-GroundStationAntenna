# Imports
import socket
import time
from skyfield.api import load, wgs84


# Config
SATELLITE_NAME = "ACS3"
TLE_URL = "https://celestrak.org/NORAD/elements/weather.txt"
OBSERVER_LAT = 42.3770
OBSERVER_LON = -71.1167
OBSERVER_ELEV_M = 10
ROTCTLD_HOST = "100.103.23.51"
ROTCTLD_PORT = 4533
UPDATE_INTERVAL = 10


# Load TLE + satellite
ts = load.timescale()
satellites = load.tle_file(TLE_URL)
by_name = {sat.name: sat for sat in satellites}
if SATELLITE_NAME not in by_name:
    raise ValueError(f"Satellite '{SATELLITE_NAME}' not found in TLE set.")
sat = by_name[SATELLITE_NAME]
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


# Main loop
print(f"Tracking satellite: {SATELLITE_NAME}")
while True:
    t = ts.now()
    difference = sat - observer
    topocentric = difference.at(t)
    alt, az, distance = topocentric.altaz()
    az_deg = az.degrees
    el_deg = alt.degrees
    # Only track when above horizon
    if el_deg > 0:
        send_rotator(az_deg, el_deg)
        print(f"AZ: {az_deg:.2f}  EL: {el_deg:.2f}")
    else:
        print("Satellite below horizon")
    time.sleep(UPDATE_INTERVAL)
