# vim: set sw=4 st=4 ai expandtab:
###########################################################################
# Copyright (C) Aerostation/Ronald Thornton 2020-2021
# All rights reserved.
###########################################################################
"""
DBI3 common definitions/declarations

"""
import os
import sys
import threading
import collections

try:
    from datetime import timezone

    utc = timezone.utc
except ImportError:
    """Python 2 doesn't have timezone module, define UTC here."""
    from datetime import tzinfo, timedelta

    class UTC(tzinfo):
        """UTC tzinfo"""

        def utcoffset(self, dt):
            return timedelta(0)

        def tzname(self, dt):
            return "UTC"

        def dst(self, dt):
            return timedelta(0)

    utc = UTC()  # tzinfo for UTC

UTC_FMT = "%Y-%m-%d %H:%M:%S"  # strftime format for UTC output

DBI_CONF_FILE = os.path.join(os.path.expanduser("~"), ".DBI3config")  # hidden DBI3 config filename
DEF_LOG_PATH = os.path.join(os.path.expanduser("~"), "Documents", "DBI3logs")
DEF_KML_PATH = os.path.join(DEF_LOG_PATH, "kml")

# Define named tuples for DBI3 KML conversion list entries
ConversionList = collections.namedtuple(
    "ConversionList", "log_name log_filename kml_name kml_filename new_file meta_name override"
)

# Summary from dbi3_log_parse
# status - int number of GPS data records or -1 for failure
# gps_start - datetime
# gps_end - datetime
# min_altitude - Meters
# max_altitude - Meters
SummaryList = collections.namedtuple(
    "SummaryList", "status, gps_start, gps_end, min_altitude, max_altitude"
)

# Define named tuple for DBI3 LOG list entries
#  name_start - RAD26 string of start time
#  name_end - RAD26 string of end time
#  start_dt - datetime of start time
#  end_dt - datetime of end time
#  log_name - string, filename of log
#  new_file - boolean new file, does not exist on the PC
#  meta_name - string, filename of metadata
#  override - dictionary of optional metadata or None
LogList = collections.namedtuple(
    "LogList", "name_start name_end start_dt end_dt log_name new_file meta_name override"
)

# There are many additional LOG fields that can be included in the KML.  These lists are the complete set,
# and the default set used in KML conversions.  NOTE: DIFF is a calculated value=TOPT-AMBT
# 25May20 - GPS ALT and PRES ALT are automatically added based on availability and GPS preference config
DBI_ALL_LOG_FIELDS = ["ROC", "TOPT", "AMBT", "DIFF", "SOG", "COG", "BATM", "BRDT"]
DBI_DEFAULT_LOG_FIELDS = ["ROC", "TOPT", "AMBT", "DIFF", "SOG", "COG"]


class Spinner:
    """Create a thread printing a spinner character until commanded to stop.

    Other output while the spinner is running will get mixed up, so don't
    use this with verbose output.
    """

    def __init__(self):
        self.e = threading.Event()
        self.t = threading.Thread(target=self.spin, args=(self.e,))
        self.t.start()

    def stop(self):
        self.e.set()  # Flag the thread to stop
        self.t.join(2.0)

    @staticmethod
    def spin(e):
        spin_char = r"\|/-\|/-"
        while True:
            for ch in spin_char:
                sys.stdout.write(ch)
                sys.stdout.flush()
                xit = e.wait(0.2)  # wait for 1/4 sec or exit event
                sys.stdout.write("\b")
                sys.stdout.flush()
                if xit:
                    return
