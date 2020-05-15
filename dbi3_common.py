# vim: set sw=4 st=4 ai expandtab:
"""
DBI3 common definitions/declarations

"""
import collections
try:
    from datetime import timezone
    utc = timezone.utc
except ImportError:
    """Python 2 doesn't have timezone module, define here."""
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


# Define named tuples for DBI3 KML conversion list entries
ConversionList = collections.namedtuple('ConversionList',
                                        'log_name log_filename kml_name kml_filename new_file meta_name override')
SummaryList = collections.namedtuple('SummaryList', 'status, gps_start, gps_end, min_altitude, max_altitude')

# Define named tuple for DBI3 LOG list entries
LogList = collections.namedtuple('LogList', 'name_start name_end start_dt end_dt log_name new_file meta_name override')

# There are many additional LOG fields that can be included in the KML.  These lists are the complete set,
# and the default set used in KML conversions.  NOTE: DIFF is a calculated value=TOPT-AMBT
DBI_ALL_LOG_FIELDS = ['ROC', 'TOPT', 'AMBT', 'DIFF', 'SOG', 'COG', 'BATM', 'BRDT']
DBI_DEFAULT_LOG_FIELDS = ['ROC', 'TOPT', 'AMBT', 'DIFF', 'SOG', 'COG']

# Metadata log config files can alter the converted output of individual logs.  The available keys are
METADATA_CONFIG_ATTR = ["altitudemode",
                        "altitude_offset",
                        "extend_to_ground",
                        "kml_use_metric",
                        "kml_fields",
                        "trim_start_time",
                        "trim_end_time",
                        "track_note"]
