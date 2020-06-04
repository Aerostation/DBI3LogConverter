#!/usr/bin/env python
# vim: set shiftwidth=4 softtabstop=4 autoincrement expandtab:
###########################################################################
# Copyright (C) Aerostation/Ronald Thornton 2020
# All rights reserved.
###########################################################################
"""Classes to parse and convert DBI3 log files"""

from __future__ import print_function
import os
import json
from datetime import datetime
from datetime import timedelta
from simplekml import Kml, Snippet, Types
import math
import re

try:
    from dbi3_common import ConversionList, SummaryList, utc, DBI_DEFAULT_LOG_FIELDS
    from dbi3_log_downloads import DBI3LogDownload
    from dbi3_config_options import Dbi3ConfigOptions, Dbi3ConversionOptions
except ImportError:
    from .dbi3_common import ConversionList, SummaryList, utc, DBI_DEFAULT_LOG_FIELDS
    from .dbi3_log_downloads import DBI3LogDownload
    from .dbi3_config_options import Dbi3ConfigOptions, Dbi3ConversionOptions

TWO_SECONDS = timedelta(seconds=2)  # time increment between data records
KML_LINE_COLOR = 'ff0000ff'  # hex aabbggrr
KML_START_COLOR = 'ff00ff00'
KML_END_COLOR = 'ff0000ff'

# Required start record, data record, and end record fields - to validate log record content
START_FIELDS = ['FWVER', 'SN', 'DATE', 'TIME']
DATA_FIELDS = ['ALT', 'ROC', 'AMBT', 'GPSS', 'SOG', 'COG', 'LONG', 'LAT', 'TOPTS', 'TOPT', 'BATM', 'BRDT']
END_FIELDS = ['DATE', 'TIME']


class Dbi3Log:
    """Parses a DBI3 log file into data arrays and computes some
    summary values across the log.
    """

    def __init__(self, kml_cfg, filename, sn=None):
        """Initialize the DBI3LogConversion object
        
        Class will parse DBI3 track data from the log.

        :param Dbi3ConversionOptions kml_cfg:
        :param str filename:  Full path to DBI3 log file
        :param str sn:  optional DBI3 SN if known at constructor time

        """

        self.filename = filename
        self.dbi3_sn = sn
        self.kml_cfg = kml_cfg
        self.dbi3_fwver = None

        self.proc_log = ''  # Accumulate print output from the entire conversion

        self.total_log_recs = 0
        self.data_recs = 0
        self.trim_recs = 0
        self.bad_recs = 0
        # Monitor min/max track data to calculate a bounding box for view
        self.min_lon = 180.0
        self.max_lon = -180.0
        self.min_lat = 90.0
        self.max_lat = -90.0

        # "Trip Computer" fields.  Summary fields of a given track.
        self.elapsed_dist = 0.0  # summation of Meters between pairs of points
        self.max_sog = 0.0  # Max SOG in M/s seen
        self.max_computed_sog = 0.0  # Using sog computed between track points
        self.min_altitude = None  # Min ALT in Meters
        self.max_altitude = None  # Max ALT in Meters
        self.min_gps_msl = None
        self.max_gps_msl = None

        self.kml_start_lat = None  # location for start/end pushpins
        self.kml_start_lon = None
        self.kml_end_lat = None
        self.kml_end_lon = None

        # fw ver 1.3 added GPS altitude to log records.  We adapt to old records, while we can
        # prefer (via config) to use GPS in the track points we fall back to pressure altitude
        # when GPS in not available.  This indicates which went into the KML coord.
        self.kml_coord_alt_gps = False

        # initialize data lists to construct the KML output.  Values are converted to
        # metric/imperial per config.
        self.kml_start_time = None  # datetime of the first GPS data line
        self.kml_end_time = None  # datetime of the last GPS data line
        self.kml_when = []  # track point timestamp
        self.kml_lat = []  # floating point degrees +=N -=S
        self.kml_lon = []  # floating point degrees +=E -=W
        self.kml_alt = []  # barometric altitude
        self.kml_bar = []  # barometric hecto Pascal
        self.kml_coord = []  # tuples: lat, lon, alt(meters)
        self.kml_gps_msl = []
        self.kml_a_temp = []
        self.kml_t_temp = []
        self.kml_diff_t = []
        self.kml_cog = []
        self.kml_sog = []
        self.kml_roc = []
        self.kml_batm = []
        self.kml_brdt = []

    def dbi3_log_parse(self):
        """Function to read and parse a DBI3 log file for later conversion

        :return SummaryStatus: Log summary
        """
        debug = False

        # Determine unit conversion for additional data fields
        # Allow additional data fields to be english or metric
        if not self.kml_cfg.kml_use_metric:
            temp_is_f = True     # False=centegrade
            alt_is_ft = True     # False=meters
            spd_is_mph = True    # False=kph
            roc_is_fps = True    # False=meters per second
        else:
            temp_is_f = False
            roc_is_fps = False
            spd_is_mph = False
            alt_is_ft = False

        # After fw ver 1.2, the log added GPS Altitude.  If check the first data record
        # to determine if we have it.
        has_msl = None

        MISSING_TOPT_F = 100.0  # when TOPT is missing, we display this default data
        MISSING_TOPT_C = 40.0  # - or this

        log_state = 1  # 1=expecting start line, 2=records
        with open(self.filename) as myfile:
            rec_time = None
            # calculate elapsed distance by summing distance between last and current point
            last_lat = None
            last_lon = None
            for line in myfile:
                self.total_log_recs += 1
                logvars = {}
                try:
                    line = line.rstrip('\r\n')
                    arg_pairs = line.split(" ")
                    for p in arg_pairs:  # type: str
                        var, val = p.split("=")  # type: (str, str)
                        logvars[var] = val
                except Exception as e:
                    print('Exception parsing line {} is: {}'.format(line, e))
                    self.bad_recs += 1
                    continue

                if 'DATE' in list(logvars.keys()):
                    # datetime from a start or end line
                    log_datetime = datetime.strptime(logvars['DATE'] + ' ' + logvars['TIME'], '%Y-%m-%d %H:%M:%S')
                else:
                    log_datetime = None

                if log_state == 1:  # Expecting the start line from the log file
                    missing_key = self.__field_check(START_FIELDS, logvars)
                    if missing_key is not None:
                        print('Start record missing field ' + missing_key)
                        break
                    start_datetime = log_datetime
                    rec_time = log_datetime  # first data record timestamp is start
                    self.dbi3_fwver = logvars['FWVER']
                    # fw ver 1.2 had a dummy SN in the log header so we override by extracting from the
                    # DBI3 serial cli, but if that wasn't supplied then use the log field.
                    if self.dbi3_sn is None:
                        self.dbi3_sn = logvars['SN']
                    log_state = 2
                    self.proc_log += '  Start time ' + start_datetime.isoformat(' ')
                elif log_state > 1 and log_datetime is not None:
                    # START record was processed, the next record with a DATE is the END record
                    end_datetime = log_datetime
                    missing_key = self.__field_check(END_FIELDS, logvars)
                    if missing_key is None:
                        log_state = 3
                        if self.kml_start_time is not None:
                            self.proc_log += ' --First GPS record ' + self.kml_start_time.isoformat(' ')
                        self.proc_log += '\n  Total records={}  data records={}  trim records={}  bad records={}'.\
                            format(self.total_log_recs, self.data_recs, self.trim_recs, self.bad_recs)
                        self.proc_log += '\n  End time ' + end_datetime.isoformat(' ')
                        if self.kml_end_time is not None:
                            self.proc_log += ' --Last GPS record ' + self.kml_end_time.isoformat(' ')
                    else:
                        print('End record missing field ' + missing_key)
                    break
                else:
                    # This should be a DATA record
                    missing_key = self.__field_check(DATA_FIELDS, logvars)
                    if missing_key is None:
                        if logvars['GPSS'] == '0':
                            ####
                            # This is a data record and it has GPS data
                            ####
                            # Check for start/end time trim
                            if self.kml_cfg.trim_start_time is not None and rec_time < self.kml_cfg.trim_start_time:
                                self.trim_recs += 1
                                continue
                            elif self.kml_cfg.trim_end_time is not None and rec_time > self.kml_cfg.trim_end_time:
                                self.trim_recs += 1
                                continue

                            self.data_recs += 1

                            if debug:
                                print('Record ' + rec_time.isoformat('T') + ' ' + logvars['LAT'] +
                                      ' ' + logvars['LONG'])

                            # calculate and accumulate KML data
                            latitude = self.__ddmm2d(logvars['LAT'])
                            self.kml_lat.append(latitude)
                            longitude = self.__ddmm2d(logvars['LONG'])
                            self.kml_lon.append(longitude)
                            # calculate min/max lat and lon so we can construct a display bounding box
                            self.min_lat = min(self.min_lat, latitude)
                            self.max_lat = max(self.max_lat, latitude)
                            self.min_lon = min(self.min_lon, longitude)
                            self.max_lon = max(self.max_lon, longitude)
                            # Append the time and coordinate lists
                            self.kml_when.append(rec_time.isoformat('T'))

                            altitude = float(logvars['ALT'])
                            if self.kml_cfg.altitude_offset is not None: altitude += self.kml_cfg.altitude_offset
                            self.kml_alt.append(
                                round(altitude if self.kml_cfg.kml_use_metric else conv_M_to_ft(altitude), 1))

                            # if we have GPS altitude available, determine which we use in the coordinates
                            if has_msl is None:  # determine if the data record includes GPS altitude
                                has_msl = logvars.get('MSLALT') is not None
                                # determine if we have and prefer GPS altitude for the track points
                                self.kml_coord_alt_gps = has_msl and self.kml_cfg.prefer_gps
                            if has_msl:
                                gps_msl = float(logvars['MSLALT'])
                                self.max_gps_msl = gps_msl if self.max_gps_msl is None or gps_msl > self.max_gps_msl \
                                    else self.max_gps_msl
                                self.min_gps_msl = gps_msl if self.min_gps_msl is None or gps_msl < self.min_gps_msl \
                                    else self.min_gps_msl
                                self.kml_gps_msl.append(
                                    round(gps_msl if self.kml_cfg.kml_use_metric else conv_M_to_ft(gps_msl), 1))

                            # Select the correct pressure/GPS altitude for coordinates
                            coord_alt = gps_msl if self.kml_coord_alt_gps else altitude

                            self.max_altitude = coord_alt if self.max_altitude is None or coord_alt > self.max_altitude \
                                else self.max_altitude
                            self.min_altitude = coord_alt if self.min_altitude is None or coord_alt < self.min_altitude \
                                else self.min_altitude

                            # KML coordinate tuple
                            self.kml_coord.append((longitude, latitude, coord_alt))

                            #
                            # For trip stats, sum the total distance traveled, max speed, min/max altitude
                            #
                            if last_lat is not None:
                                point_dist = calc_distance((last_lat, last_lon), (latitude, longitude))
                                self.elapsed_dist += point_dist
                                computed_sog = point_dist / 2.0  # fixed time between point is 2 seconds
                                self.max_computed_sog = max(self.max_computed_sog, computed_sog)
                            last_lat = latitude  # save last lat/lon for the next time thru the loop
                            last_lon = longitude

                            #
                            # Additional data fields

                            # Round floating point data to a reasonable accuracy (e.g. 1 or 2 digit)
                            #
                            amb_temp = conv_C_to_F(float(logvars['AMBT'])) if temp_is_f else float(logvars['AMBT'])
                            self.kml_a_temp.append(round(amb_temp, 1))

                            self.kml_bar.append(round(float(logvars['BAR']), 2))

                            if logvars['TOPTS'] == '1':  # Top temp value is valid
                                top_temp = conv_C_to_F(float(logvars['TOPT'])) if temp_is_f else float(logvars['TOPT'])
                            else:  # Top temp value is missing
                                top_temp = MISSING_TOPT_F if temp_is_f else MISSING_TOPT_C
                            self.kml_t_temp.append(round(top_temp, 1))

                            self.kml_diff_t.append(round(top_temp - amb_temp, 1))

                            sog = float(logvars['SOG'])
                            self.max_sog = max(self.max_sog, sog)
                            sog = round(conv_M_to_mi(sog * 60 * 60) if spd_is_mph else sog, 1)
                            self.kml_sog.append(sog)

                            self.kml_cog.append(round(float(logvars['COG']), 1))

                            roc = float(logvars['ROC'])
                            roc = round(conv_M_to_ft(roc * 60) if roc_is_fps else roc, 1)
                            self.kml_roc.append(roc)

                            self.kml_batm.append(round(float(logvars['BATM']), 2))

                            brdt = float(logvars['BRDT'])
                            brdt = round(conv_C_to_F(brdt) if temp_is_f else brdt, 2)
                            self.kml_brdt.append(brdt)
                            # Finished a valid data record, capture the first time as kml_start,
                            # update kml_end on each valid data record so we have the last time.
                            if self.kml_start_time is None:
                                self.kml_start_time = rec_time
                                self.kml_start_lat = latitude
                                self.kml_start_lon = longitude
                            self.kml_end_time = rec_time
                    else:
                        print('Data record missing field ' + missing_key)
                        self.bad_recs += 1
                    # Do we increment the time before or after the data records?
                    rec_time += TWO_SECONDS
            self.kml_end_lat = last_lat
            self.kml_end_lon = last_lon

            rtn_val = self.data_recs if log_state == 3 else -1

            return SummaryList(status=rtn_val,
                               gps_start=self.kml_start_time,
                               gps_end=self.kml_end_time,
                               min_altitude=self.min_altitude,
                               max_altitude=self.max_altitude)

    @staticmethod
    def __field_check(req_fields, myvars):
        """Check that all required data fields exists.

        Args:
            req_fields - list of field names
            myvars - list of parsed NAME=VALUE parsed fields

        Returns:
            None - success, no missing field
            str - the name of the first missing field detected
        """
        for r_key in req_fields:
            if r_key not in myvars:
                return r_key
        return None

    @staticmethod
    def __ddmm2d(dm):
        """Convert DBI3 ddmm.mmmmi latitude or longitude to floating point dd.ddd

        i - hemisphere indicator NSEW
        m - floating point minutes
        d - integer degrees

        The degree field can be 1-3 digits, minutes integer is always 2 so
        this conversion works for latitude or longitude.
        i = W or S returns negative degrees.

        Args:
            dm - string of the [d[d]]dmm.mmmmi

        Return:
            floating point degrees equivelent of dm
        """
        hemi = dm[-1:]
        dm = dm[:-1]
        min_dec = dm.find('.')
        deg = dm[:min_dec - 2]
        minutes = dm[min_dec - 2:]
        latlon = float(deg) + float(minutes) / 60.0
        if hemi == 'W' or hemi == 'S':
            latlon = 0.0 - latlon
        return latlon


class Dbi3LogConversion:
    """
    Main class to drive conversions.

    Parse the DBI3 log file, then provide methods to output various conversion formats.
    """

    def __init__(self, filename, config):
        """
        Initialize the config object, parse the log file.

        :param filename: DBI3 log filename
        :param Dbi3ConfigOptions config:  Application options object
        """

        self.filename = filename

        self.app_config = config
        self.kml_cfg = Dbi3ConversionOptions(filename, config)
        if self.app_config.verbose:
            print('Dbi3LogConversion - kml_cfg - {}'.format(self.kml_cfg))

        self.dbi3_log = Dbi3Log(self.kml_cfg, self.filename)  # Log object for a specific DBI3 log
        self.parse_summary = self.dbi3_log.dbi3_log_parse()

    def log_summary(self):
        """Return the summary generated during initial log_parse()"""
        return self.parse_summary

    def kml_convert(self, base_name):
        """Function to read and convert a DBI3 log file to KML format

        If called with base_name=None, parse the log file but return a SummaryList with
        parse status and skip the actual KML creation.

        Args:
            base_name: Base path and filename for output - add extension

        Returns: int, str
            int - 0=success, 1=warning, -1=error
            str - Success info or warning/error message
        """
        # TODO handle optional GPS altitude completely
        #
        # Determine unit conversion for additional data fields
        # Allow additional data fields to be english or metric
        if not self.kml_cfg.kml_use_metric:
            temp_is_f = True     # False=centegrade
            alt_is_ft = True     # False=meters
            spd_is_mph = True    # False=kph
            roc_is_fps = True    # False=meters per second
        else:
            temp_is_f = False
            roc_is_fps = False
            spd_is_mph = False
            alt_is_ft = False

        # check the status of the log_parse()
        if self.dbi3_log.data_recs == 0:
            return 1, 'No GPS data records, skip KML file generations'
        elif self.dbi3_log.data_recs < 0:
            return -1, 'No END record, skip KML file generation'

        # fw ver 1.3 added GPS altitude.  If we have both we use the preferred (pressure/GPS)
        # altitude in the track points and add the other as an additional data field.
        add_pressure_alt = False
        add_gps_alt = False
        if len(self.dbi3_log.kml_gps_msl) > 0:
            if self.dbi3_log.kml_coord_alt_gps:
                add_pressure_alt = True
            else:
                add_gps_alt = True

        # Establish unit of measure strings depending on Metric vs English measures
        tempStr = 'F' if temp_is_f else 'C'
        sogStr = 'MPH' if spd_is_mph else 'mps'
        distStr = 'mi' if spd_is_mph else 'm'
        rocStr = 'FPM' if roc_is_fps else 'mps'
        altStr = 'ft' if alt_is_ft else 'm'

        avg_sog = self.dbi3_log.elapsed_dist / (self.dbi3_log.kml_end_time - self.dbi3_log.kml_start_time).total_seconds()  # in meters/second

        e_hr, remainder = divmod(int((self.dbi3_log.kml_end_time - self.dbi3_log.kml_start_time).total_seconds()), 3600)
        e_min, e_sec = divmod(remainder, 60)

        if self.kml_cfg.track_note:
            t_note = '<b>{}</b>\n'.format(self.kml_cfg.track_note)
        else:
            t_note = ''

        # Our 'trip computer' values are formatted into a KML description string to be included in
        # the track object.
        property_table = '''<![CDATA[{}\
<table>
<tr><td><b>Distance </b>{:.2f} {}</td><tr>
<tr><td><b>Min Alt </b>{:.2f} {}</td><tr>
<tr><td><b>Max Alt </b>{:.2f} {}</td><tr>
<tr><td><b>Avg Speed </b>{:.2f} {}</td><tr>
<tr><td><b>Max Speed </b>{:.2f}(SOG {:.2f}) {}</td><tr>
<tr><td><b>Start Time </b>{}</td><tr>
<tr><td><b>End Time </b>{}</td><tr>
<tr><td><b>Elapsed </b>{:02d}:{:02d}:{:02d}</td><tr>
<tr><td>DBI3  {}  FWVER {}</td><tr>
<tr><td>Formatted {}</td><tr>
</table>]]>'''.format(t_note,
                      conv_M_to_mi(self.dbi3_log.elapsed_dist) if spd_is_mph else self.dbi3_log.elapsed_dist, distStr,
                      conv_M_to_ft(self.dbi3_log.min_altitude) if alt_is_ft else self.dbi3_log.min_altitude, altStr,
                      conv_M_to_ft(self.dbi3_log.max_altitude) if alt_is_ft else self.dbi3_log.max_altitude, altStr,
                      conv_M_to_mi(avg_sog * 60 * 60) if spd_is_mph else avg_sog, sogStr,
                      conv_M_to_mi(self.dbi3_log.max_computed_sog * 60 * 60) if spd_is_mph else
                                                                                self.dbi3_log.max_computed_sog,
                      conv_M_to_mi(self.dbi3_log.max_sog * 60 * 60) if spd_is_mph else self.dbi3_log.max_sog,
                      sogStr,
                      self.dbi3_log.kml_start_time.strftime("%Y-%m-%d %H:%M:%S"),
                      self.dbi3_log.kml_end_time.strftime("%Y-%m-%d %H:%M:%S"),
                      e_hr, e_min, e_sec,
                      self.app_config.sn, self.dbi3_log.dbi3_fwver,
                      datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        #
        # Moving on to KML generation

        # Create the KML document
        kml = Kml(open=1, name=self.dbi3_log.kml_start_time.strftime('%Y%m%d_%H%MZ_DBI3'), description=property_table)
#            doc = kml.newdocument(name=kml_start.strftime('%Y%m%d_%H%MZ_Track'), description=property_table)
                              # snippet=Snippet('DBI3LogConversion run ' + datetime.now().isoformat(' ')))
        doc = kml
        # kml timespan is based on the first and last valid data record, not DBI3 log start/end.
        # doc.lookat.gxtimespan.begin = kml_start.isoformat('T')
        # doc.lookat.gxtimespan.end = kml_end.isoformat('T')
        # doc.lookat.longitude = max_lon - ((max_lon - min_lon) / 2)
        # doc.lookat.latitude = max_lat - ((max_lat - min_lat) / 2)
        # doc.lookat.range = calc_distance((min_lat, min_lon), (max_lat, max_lon)) * 1.5

        # Create a folder
        # fol = doc.newfolder(name='Tracks')
        fol = doc

        # Create a schema for extended data
        schema = kml.newschema()
        if add_gps_alt:
            schema.newgxsimplearrayfield(name='g_alt', type=Types.float, displayname='GPS ALT ' + altStr)
        if add_pressure_alt:
            schema.newgxsimplearrayfield(name='p_alt', type=Types.float, displayname='PRES ALT ' + altStr)
        if 'AMBT' in self.kml_cfg.kml_fields:
            schema.newgxsimplearrayfield(name='a_temp', type=Types.float, displayname='Ambient ' + tempStr)
        if 'TOPT' in self.kml_cfg.kml_fields:
            schema.newgxsimplearrayfield(name='t_temp', type=Types.float, displayname='Top ' + tempStr)
        if 'DIFF' in self.kml_cfg.kml_fields:
            schema.newgxsimplearrayfield(name='d_temp', type=Types.float, displayname='Diff ' + tempStr)
        if 'COG' in self.kml_cfg.kml_fields:
            schema.newgxsimplearrayfield(name='cog', type=Types.float, displayname='COG')
        if 'SOG' in self.kml_cfg.kml_fields:
            schema.newgxsimplearrayfield(name='sog', type=Types.float, displayname='SOG ' + sogStr)
        if 'ROC' in self.kml_cfg.kml_fields:
            schema.newgxsimplearrayfield(name='roc', type=Types.float, displayname='ROC ' + rocStr)
        if 'BATM' in self.kml_cfg.kml_fields:
            schema.newgxsimplearrayfield(name='batm', type=Types.float, displayname='BAT V')
        if 'BRDT' in self.kml_cfg.kml_fields:
            schema.newgxsimplearrayfield(name='brdt', type=Types.float, displayname='BRD ' + tempStr)

        # Create a new track in the folder
        trk = fol.newgxtrack(name=self.dbi3_log.kml_start_time.strftime('%Y%m%d_%H%MZ Track'),
                             altitudemode=self.kml_cfg.altitudemode,  # absolute, clampToGround, relativeToGround
                             extrude=self.kml_cfg.extend_to_ground,
                             description=property_table)
        trk.lookat.gxtimespan.begin = self.dbi3_log.kml_start_time.isoformat('T')
        trk.lookat.gxtimespan.end = self.dbi3_log.kml_end_time.isoformat('T')
        trk.lookat.longitude = self.dbi3_log.max_lon - ((self.dbi3_log.max_lon - self.dbi3_log.min_lon) / 2)
        trk.lookat.latitude = self.dbi3_log.max_lat - ((self.dbi3_log.max_lat - self.dbi3_log.min_lat) / 2)
        trk.lookat.range = calc_distance((self.dbi3_log.min_lat, self.dbi3_log.min_lon),
                                         (self.dbi3_log.max_lat, self.dbi3_log.max_lon)) * 1.5

        # Apply the above schema to this track
        trk.extendeddata.schemadata.schemaurl = schema.id

        #
        # Add all the information to the track
        #
        trk.newwhen(self.dbi3_log.kml_when)  # Each item in the give nlist will become a new <when> tag
        trk.newgxcoord(self.dbi3_log.kml_coord)

        # Add points to the start and end of the track
        pnt = fol.newpoint(name='Start', coords=[(self.dbi3_log.kml_start_lon, self.dbi3_log.kml_start_lat)])
        pnt.description = self.dbi3_log.kml_start_time.isoformat('T')
        pnt.style.labelstyle.color = KML_START_COLOR
        pnt.style.iconstyle.icon.href = 'http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png'
        pnt = fol.newpoint(name='Finish', coords=[(self.dbi3_log.kml_end_lon, self.dbi3_log.kml_end_lat)])
        pnt.description = self.dbi3_log.kml_end_time.isoformat('T')
        pnt.style.labelstyle.color = KML_END_COLOR
        pnt.style.iconstyle.icon.href = 'http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png'

        # Add any additional data fields that are requested
        if add_gps_alt:
            trk.extendeddata.schemadata.newgxsimplearraydata('g_alt', self.dbi3_log.kml_gps_msl)
        if add_pressure_alt:
            trk.extendeddata.schemadata.newgxsimplearraydata('p_alt', self.dbi3_log.kml_alt)
        if 'AMBT' in self.kml_cfg.kml_fields:
            trk.extendeddata.schemadata.newgxsimplearraydata('a_temp', self.dbi3_log.kml_a_temp)
        if 'TOPT' in self.kml_cfg.kml_fields:
            trk.extendeddata.schemadata.newgxsimplearraydata('t_temp', self.dbi3_log.kml_t_temp)
        if 'DIFF' in self.kml_cfg.kml_fields:
            trk.extendeddata.schemadata.newgxsimplearraydata('d_temp', self.dbi3_log.kml_diff_t)
        if 'COG' in self.kml_cfg.kml_fields:
            trk.extendeddata.schemadata.newgxsimplearraydata('cog', self.dbi3_log.kml_cog)
        if 'SOG' in self.kml_cfg.kml_fields:
            trk.extendeddata.schemadata.newgxsimplearraydata('sog', self.dbi3_log.kml_sog)
        if 'ROC' in self.kml_cfg.kml_fields:
            trk.extendeddata.schemadata.newgxsimplearraydata('roc', self.dbi3_log.kml_roc)
        if 'BATM' in self.kml_cfg.kml_fields:
            trk.extendeddata.schemadata.newgxsimplearraydata('batm', self.dbi3_log.kml_batm)
        if 'BRDT' in self.kml_cfg.kml_fields:
            trk.extendeddata.schemadata.newgxsimplearraydata('brdt', self.dbi3_log.kml_brdt)

        # Styling
        trk.stylemap.normalstyle.iconstyle.icon.href = 'http://earth.google.com/images/kml-icons/track-directional/track-0.png'
        trk.stylemap.normalstyle.linestyle.color = KML_LINE_COLOR
        trk.stylemap.normalstyle.linestyle.width = 3
        trk.stylemap.highlightstyle.iconstyle.icon.href = 'http://earth.google.com/images/kml-icons/track-directional/track-0.png'
        trk.stylemap.highlightstyle.iconstyle.scale = 1.2
        trk.stylemap.highlightstyle.linestyle.color = KML_LINE_COLOR
        trk.stylemap.highlightstyle.linestyle.width = 8

        # Save the kml to file
        kml.save(base_name + ".kml")

        return 0, self.dbi3_log.proc_log

    def csv_convert(self, csv_filename):
        """
        Quick demo of csv output from existing log parse.

        Should adapt column header to metric/imperial

        :param str csv_filename:
        :returns:
            - status(int):    status
            - proc_log(str):  detail log of processing
        """
        # check the status of the log_parse()
        if self.dbi3_log.data_recs == 0:
            return 1, 'No GPS data records, skip KML file generations'
        elif self.dbi3_log.data_recs < 0:
            return -1, 'No END record, skip KML file generation'

        with open(csv_filename, 'w') as csv_file:
            if len(self.dbi3_log.kml_gps_msl) > 0:
                print('timestamp,alt,gps_alt,lat,lon,head,speed,bar,temp,diff_temp', file=csv_file)

                for t_pnt in zip(self.dbi3_log.kml_when,
                                 self.dbi3_log.kml_alt,
                                 self.dbi3_log.kml_gps_msl,
                                 self.dbi3_log.kml_lat,
                                 self.dbi3_log.kml_lon,
                                 self.dbi3_log.kml_cog,
                                 self.dbi3_log.kml_sog,
                                 self.dbi3_log.kml_bar,
                                 self.dbi3_log.kml_a_temp,
                                 self.dbi3_log.kml_diff_t):
                    print('{},{},{},{},{},{},{},{},{},{}'.format(*t_pnt), file=csv_file)

            else:
                print('timestamp,alt,lat,lon,head,speed,bar,temp,diff_temp', file=csv_file)

                for t_pnt in zip(self.dbi3_log.kml_when,
                                 self.dbi3_log.kml_alt,
                                 self.dbi3_log.kml_lat,
                                 self.dbi3_log.kml_lon,
                                 self.dbi3_log.kml_cog,
                                 self.dbi3_log.kml_sog,
                                 self.dbi3_log.kml_bar,
                                 self.dbi3_log.kml_a_temp,
                                 self.dbi3_log.kml_diff_t):
                    print('{},{},{},{},{},{},{},{},{}'.format(*t_pnt), file=csv_file)

        return 0, '  CSV Write {} complete'.format(os.path.basename(csv_filename))


def conv_C_to_F(tempC):
    """Convert Centigrade to Fahrenheit."""
    return 9.0 / 5.0 * tempC + 32


def conv_M_to_ft(meters):
    """Convert Meters to feet."""
    return meters * 3.28084


def conv_ft_to_M(feet):
    """Convert feet to Meters."""
    return feet / 3.28084


def conv_M_to_mi(meters):
    """Convert Meters to miles."""
    return meters * 0.000621371


def calc_distance(origin, destination):
    """Give distance between two points in Meters.

    :param list,floats origin: decimal lat,lon of the first point
    :param list,floats destination: decimal lat,lon of the second point
    :return float: Distance in Meters
    """
    lat1, lon1 = origin
    lat2, lon2 = destination
    radius = 6371.0  # km

    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) * math.sin(dlat / 2) + math.cos(math.radians(lat1)) \
        * math.cos(math.radians(lat2)) * math.sin(dlon / 2) * math.sin(dlon / 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    d = radius * c

    return d * 1000.0


class Dbi3KmlList:
    """Manipulate the list for DBI3 log to KML conversions.

    Constructs a list of available log conversions, defaults the select to new log files only.

    New files can either be any log that doesn't have a current KML, or only logs later than
    the current latest KML.  Default is the later.

    Allows editing of the selections.  The list can then be used to drive multiple conversions.
    """

    def __init__(self, config):
        """

        :param Dbi3ConfigOptions config:  Application config object
        """
        self.app_config = config
        self.log_sn_path = os.path.join(config.log_path, config.sn)
        self.conversion_list = []
        self.debug = False
        self.new_limit = None

        # To determine "new" KML we need to know the latest KML in kml_path
        dt = None
        for item in sorted(os.listdir(config.kml_path), reverse=True):
            if not os.path.isfile(os.path.join(config.kml_path, item)):
                continue
            try:
                # This strptime also verifies the filename format
                dt = datetime.strptime(item, "%Y%m%d_%H%M_{}.kml".format(config.sn))
            except ValueError as e:
                # Could be the kml didn't match our current SN for logs
                if self.debug:
                    print(('Parse error of {}:{}'.format(item, e)))
                continue
            if dt is not None:
                self.new_limit = dt.replace(tzinfo=utc) + timedelta(minutes=1)  # make new_limit timezone aware
                if config.verbose:
                    print('DBI3 KML computed new file threshold: {}'.format(self.new_limit))
                break

    def refresh_list(self):
        """Builds list of available LOG files and selects those without a corresponding KML conversion.

        For each DBI3 log file, if the corresponding kml file does not exists,
        run the conversion.

        :return list,ConversionList:
        """
        dt_limit = None
        # new_logs overrides any age_limit on list generation
        if self.app_config.CLI_new_logs and self.new_limit is not None:
            dt_limit = self.new_limit
        elif self.app_config.CLI_age_limit is not None:
            dt_limit = self.app_config.CLI_age_limit

        self.conversion_list = []
        # If we have an age limit, construct a matching filename for comparison
        age_limit_name = None
        if dt_limit is not None:
            age_limit_name = dt_limit.strftime('%Y_%m_%d_%H_%M_%S.log')

        # regex to extract timestamp fields from DBI3 log name format
        prog = re.compile('^(\d{4})_(\d\d)_(\d\d)_(\d\d)_(\d\d)_(\d\d).log$')
        for log_name in sorted(os.listdir(self.log_sn_path)):
            name_parts = prog.match(log_name)
            log_filename = os.path.join(self.log_sn_path, log_name)
            if name_parts is not None and os.path.isfile(log_filename) and (
                    age_limit_name is None or log_name > age_limit_name):
                # log_name matches the re, is a file, and exceeds the age limit if defined
                selected = False
                data = None
                kml_name = name_parts.expand('\\1\\2\\3_\\4\\5_') + self.app_config.sn
                kml_filename = os.path.join(self.app_config.kml_path, kml_name)
                log_metaname = os.path.join(self.log_sn_path, '.' + log_name[0:-4])  # create metadata name from log name
                if not os.path.isfile(kml_filename + '.kml'):
                    selected = True
                if os.path.isfile(log_metaname):
                    # meta file data to override some conversion settings
                    with open(log_metaname, 'r') as meta:
                        data = json.load(meta)
                self.conversion_list.append(ConversionList(log_name=log_name,
                                                           log_filename=log_filename,
                                                           kml_name=kml_name,
                                                           kml_filename=kml_filename,
                                                           new_file=selected,
                                                           meta_name=log_metaname,
                                                           override=data))

        return self.conversion_list
