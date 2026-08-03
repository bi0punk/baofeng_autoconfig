import logging
import math
import os
import sys

import serial

log = logging.getLogger(__name__)


def cfg_setup_chirp():
    os.environ.setdefault("CHIRP_TESTENV", "1")
    sys.path.insert(0, "/usr/lib/python3/dist-packages")


def csv_row_to_power(power_str):
    try:
        power_w = float(power_str)
    except (ValueError, TypeError):
        power_w = 1.0
    if power_w <= 0:
        power_w = 1.0
    target_dbm = 10.0 * math.log10(power_w * 1000.0)
    best = POWER_LEVELS[0]
    for pl in POWER_LEVELS:
        if abs(float(pl) - target_dbm) < abs(float(best) - target_dbm):
            best = pl
    return best


def safe_float(value, default=0.0):
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


from chirp import chirp_common

POWER_LEVELS = [
    chirp_common.PowerLevel("High", watts=5.00),
    chirp_common.PowerLevel("Med", watts=3.00),
    chirp_common.PowerLevel("Low", watts=1.00),
]


def open_serial_ok(port, timeout=0.3):
    try:
        s = serial.Serial(port=port, baudrate=9600, timeout=timeout)
        return s
    except Exception:
        log.debug("No se pudo abrir puerto %s", port, exc_info=True)
        return None
