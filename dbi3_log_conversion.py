#!/usr/bin/env python
# vim: set sw=4 st=4 ai expandtab:
"""Program to convert DBI3 log files to KML"""

# TODO: Add green pushpin at the start GPS, red pushpin at the end GPS
import os
import json
from datetime import datetime
from datetime import timedelta
from simplekml import Kml, Snippet, Types
import math
import re

from dbi3_common import ConversionList, SummaryList, utc, dbi_def_log_fields
from dbi3_log_downloads import DBI3LogDownload

two_seconds = timedelta(seconds=2)  # time increment between data records
kml_line_color = 'ff0000ff'  # hex aabbggrr
kml_start_color = 'ff00ff00'
kml_end_color = 'ff0000ff'

# Required start record, data record, and end record fields - to validate log record content
start_fields = ['FWVER', 'SN', 'DATE', 'TIME']
data_fields = ['ALT', 'ROC', 'AMBT', 'GPSS', 'SOG', 'COG', 'LONG', 'LAT', 'TOPTS', 'TOPT', 'BATM', 'BRDT']
end_fields = ['DATE', 'TIME']

class Dbi3LogConversion:
    config_attr = ["altitudemode",
                   "altitude_offset",
                   "extend_to_ground",
                   "kml_use_metric",
                   "kml_fields",
                   "trim_start_time",
                   "trim_end_time"]
    kml_do_fields = {}

    def __init__(self, filename, sn=None,
                 altitudemode=None, altitude_offset=None,
                 extend_to_ground=None, verbose=None,
                 fields_choice=None,
                 kml_use_metric=None):
        """Initialize the DBI3LogConversion object

        Args:
            filename: full path to the LOG file
            altitudemode:

        """

        self.filename = filename
        self.dbi3_sn = sn

        # Establish config defaults
        self.altitudemode = "absolute"
        self.altitude_offset = None  # floating point
        self.extend_to_ground = True
        self.kml_fields = dbi_def_log_fields
        self.kml_use_metric = False
        self.verbose = False
        self.trim_start_time = None
        self.trim_end_time = None

        # Override defaults with optional parameters
        if altitudemode is not None: self.altitudemode = altitudemode
        if altitude_offset is not None: self.altitude_offset = altitude_offset
        if extend_to_ground is not None: self.extend_to_ground = extend_to_ground
        if fields_choice is not None: self.kml_fields = fields_choice
        if kml_use_metric is not None: self.kml_use_metric = kml_use_metric
        if verbose is not None: self.verbose = verbose

        # Optional override config from a metadata config file
        self.log_path = os.path.dirname(filename)
        self.log_file = os.path.basename(filename)
        fn, ext = os.path.splitext(self.log_file)
        self.log_meta = os.path.join(self.log_path, '.' + fn)
        if os.path.isfile(self.log_meta):
            # This log file has persisted meta data, get the config options
            with open(self.log_meta, 'r') as meta:
                data = json.load(meta)
            for fld in self.config_attr:
                if fld in data:
                    setattr(self, fld, data[fld])
            # the trim fields need to be converted to datetime.
            if self.trim_start_time is not None:
                self.trim_start_time = datetime.strptime(self.trim_start_time, "%Y%m%d%H%M%S")
            if self.trim_end_time is not None:
                self.trim_end_time = datetime.strptime(self.trim_end_time, "%Y%m%d%H%M%S")

    def kml_convert(self, base_name):
        """Function to read and convert a DBI3 log file to KML format

        Args:
            base_name: Base path and filename for output - add extension

        Returns: int, str
            int - 0=success, 1=warning, -1=error
            str - Success info or warning/error message
        """
        # TODO csv creation support has fallen out of this code.  Maybe it should be removed!

        csv_file = None  # disable csv for now

        # Determine unit conversion for additional data fields
        # Allow additional data fields to be english or metric
        if not self.kml_use_metric:
            tempIsF = True     # False=centegrade
            altIsFt = True     # False=meters
            spdIsMph = True    # False=kph
            varioIsFpm = True  # False=meters per second
        else:
            tempIsF = False
            varioIsFpm = False
            spdIsMph = False
            altIsFt = False

        debug = False

        log_state = 1  # 1=expecting start line, 2=records
        header_line = False
        tot_recs = 0
        dat_recs = 0
        trim_recs = 0
        bad_recs = 0
        # Monitor min/max track data to calculate a bounding box
        min_lon = 180.0
        max_lon = -180.0
        min_lat = 90.0
        max_lat = -90.0
        min_toptF = 100.0  # when TOPT is missing, we display this default data
        min_toptC = 40.0  # - or this

        # "Trip Computer" fields.  Summary fields of a given track.
        elapsed_dist = 0.0  # summation of Meters between pairs of points
        max_sog = None  # Max SOG in M/s seen
        max_computed_sog = None
        min_altitude = None  # Max ALT in Meters
        max_altitude = None  # Min ALT in Meters

        kml_start_lat = None
        kml_start_lon = None
        kml_end_lat = None
        kml_end_lon = None

        # initialize data lists to construct the KML output
        kml_start = None  # datetime of the first GPS data line
        kml_end = None  # datetime of the last GPS data line
        kml_when = []
        kml_coord = []
        kml_a_temp = []
        kml_t_temp = []
        kml_diff_t = []
        kml_cog = []
        kml_sog = []
        kml_roc = []
        kml_batm = []
        kml_brdt = []

        proc_log = ''  # Accumulate print output from the entire conversion

        with open(self.filename) as myfile:
            rec_time = None
            # calculate elapsed distance by summing distance between last and current point
            last_lat = None
            last_lon = None
            for line in myfile:
                tot_recs += 1
                logvars = {}
                try:
                    line = line.rstrip('\r\n')
                    arg_pairs = line.split(" ")
                    for p in arg_pairs:  # type: str
                        var, val = p.split("=")  # type: (str, str)
                        logvars[var] = val
                except Exception as e:
                    print 'Exception parsing line {} is: {}'.format(line, e)
                    bad_recs += 1
                    continue

                if 'DATE' in logvars.keys():
                    # datetime from a start or end line
                    log_datetime = datetime.strptime(logvars['DATE'] + ' ' + logvars['TIME'], '%Y-%m-%d %H:%M:%S')
                else:
                    log_datetime = None

                if log_state == 1:  # Expecting the start line from the log file
                    missing_key = self.__field_check(start_fields, logvars)
                    if missing_key is not None:
                        print 'Start record missing field ' + missing_key
                        break
                    start_datetime = log_datetime
                    rec_time = log_datetime  # first data record timestamp is start
                    dbi3_fwver = logvars['FWVER']
                    if self.dbi3_sn is None:
                        self.dbi3_sn = logvars['SN']
                    log_state = 2
                    proc_log += '  Start time ' + start_datetime.isoformat(' ')
                elif log_state > 1 and log_datetime is not None:
                    # START record was processed, the next record with a DATE is the END record
                    end_datetime = log_datetime
                    missing_key = self.__field_check(end_fields, logvars)
                    if missing_key is None:
                        log_state = 3
                        if kml_start is not None:
                            proc_log += ' --First GPS record ' + kml_start.isoformat(' ')
                        proc_log += '\n  Total records={}  data records={}  trim records={}  bad records={}'.\
                            format(tot_recs, dat_recs, trim_recs, bad_recs)
                        proc_log += '\n  End time ' + end_datetime.isoformat(' ')
                        if kml_end is not None:
                            proc_log += ' --Last GPS record ' + kml_end.isoformat(' ')
                    else:
                        print 'End record missing field ' + missing_key
                    break
                else:
                    # This should be a DATA record
                    missing_key = self.__field_check(data_fields, logvars)
                    if missing_key is None:
                        if logvars['GPSS'] == '0':
                            ####
                            # This is a data record and it has GPS data
                            ####
                            # Check for start/end time trim
                            if self.trim_start_time is not None and rec_time < self.trim_start_time:
                                trim_recs += 1
                                continue
                            elif self.trim_end_time is not None and rec_time > self.trim_end_time:
                                trim_recs += 1
                                continue

                            dat_recs += 1
                            if csv_file is not None:
                                if not header_line:
                                    print >> csv_file, 'utc_d,utc_t,alt,lat,lon,head,speed,temp'
                                    header_line = True
                                print >> csv_file, rec_time.strftime('%Y/%m/%d,%H:%M:%S,') + logvars['ALT'] + \
                                                   ',' + logvars['LAT'] + ',' + logvars['LONG'] + \
                                                   ',' + logvars['COG'] + ',' + logvars['SOG'] + \
                                                   ',' + logvars['AMBT']
                            if debug:
                                print 'Record ' + rec_time.isoformat('T') + ' ' + logvars['LAT'] + ' ' + logvars['LONG']

                            # calculate and accumulate KML data
                            kml_lat = self.__ddmm2d(logvars['LAT'])
                            kml_lon = self.__ddmm2d(logvars['LONG'])
                            # calculate min/max lat and lon so we can construct a display bounding box
                            if kml_lat < min_lat:
                                min_lat = kml_lat
                            if kml_lat > max_lat:
                                max_lat = kml_lat
                            if kml_lon < min_lon:
                                min_lon = kml_lon
                            if kml_lon > max_lon:
                                max_lon = kml_lon
                            # Append the time and coordinate lists
                            kml_when.append(rec_time.isoformat('T'))
                            altitude = float(logvars['ALT'])
                            if self.altitude_offset is not None: altitude += self.altitude_offset
                            kml_coord.append((kml_lon, kml_lat, altitude))

                            #
                            # For trip stats, sum the total distance traveled, max speed, min/max altitude
                            #
                            if last_lat is not None:
                                point_dist = calc_distance((last_lat, last_lon), (kml_lat, kml_lon))
                                elapsed_dist += point_dist
                                computed_sog = point_dist / 2.0  # fixed time between point is 2 seconds
                                if max_computed_sog is None or computed_sog > max_computed_sog:
                                    max_computed_sog = computed_sog
                            last_lat = kml_lat  # save last lat/lon for the next time thru the loop
                            last_lon = kml_lon
                            if max_altitude is None or altitude > max_altitude:
                                max_altitude = altitude
                            if min_altitude is None or altitude < min_altitude:
                                min_altitude = altitude
                            sog = float(logvars['SOG'])
                            if max_sog is None or sog > max_sog:
                                max_sog = sog

                            #
                            # Additional data fields
                            #
                            amb_temp = conv_C_to_F(float(logvars['AMBT'])) if tempIsF else float(logvars['AMBT'])
                            if logvars['TOPTS'] == '1':
                                top_temp = conv_C_to_F(float(logvars['TOPT'])) if tempIsF else float(logvars['TOPT'])
                            else:
                                top_temp = min_toptF if tempIsF else min_toptC
                            if 'AMBT' in self.kml_fields:
                                kml_a_temp.append(amb_temp)
                            if 'TOPT' in self.kml_fields:
                                kml_t_temp.append(top_temp)
                            if 'DIFF' in self.kml_fields:
                                kml_diff_t.append(top_temp - amb_temp)
                            if 'SOG' in self.kml_fields:
                                sog = float(logvars['SOG'])
                                sog = conv_M_to_mi(sog * 60 * 60) if spdIsMph else sog
                                kml_sog.append(sog)
                            if 'COG' in self.kml_fields:
                                kml_cog.append(float(logvars['COG']))
                            if 'ROC' in self.kml_fields:
                                roc = float(logvars['ROC'])
                                roc = conv_M_to_ft(roc * 60) if varioIsFpm else roc
                                kml_roc.append(roc)
                            if 'BATM' in self.kml_fields:
                                kml_batm.append(float(logvars['BATM']))
                            if 'BRDT' in self.kml_fields:
                                brdt = float(logvars['BRDT'])
                                brdt = conv_C_to_F(brdt) if tempIsF else brdt
                                kml_brdt.append(brdt)
                            # Finished a valid data record, capture the first time as kml_start,
                            # update kml_end on each valid data record so we have the last time.
                            if kml_start is None:
                                kml_start = rec_time
                                kml_start_lat = kml_lat
                                kml_start_lon = kml_lon
                            kml_end = rec_time
                    else:
                        print 'Data record missing field ' + missing_key
                        bad_recs += 1
                    # Do we increment the time before or after the data records?
                    rec_time += two_seconds
            kml_end_lat = last_lat
            kml_end_lon = last_lon

            if dat_recs == 0:
                return 1, 'No GPS data records, skip KML file generations'
            elif log_state != 3:
                return  -1, 'No END record, skip KML file generation'

            # Establish unit of measure strings depending on Metric vs English measures
            tempStr = 'F' if tempIsF else 'C'
            sogStr = 'MPH' if spdIsMph else 'mps'
            distStr = 'mi' if spdIsMph else 'm'
            rocStr = 'FPM' if varioIsFpm else 'mps'
            altStr = 'ft' if altIsFt else 'm'

            avg_sog = elapsed_dist / (kml_end - kml_start).total_seconds()  # in meters/second

            # Our 'trip computer' values are formatted into a KML description string to be included in
            # the track object.
            property_table = '''<![CDATA[\
<table>
<tr><td><b>Distance </b>{:.2f} {}</td><tr>
<tr><td><b>Min Alt </b>{:.2f} {}</td><tr>
<tr><td><b>Max Alt </b>{:.2f} {}</td><tr>
<tr><td><b>Max Speed </b>{:.2f}({:.2f}) {}</td><tr>
<tr><td><b>Avg Speed </b>{:.2f} {}</td><tr>
<tr><td><b>Start Time </b>{}</td><tr>
<tr><td><b>End Time </b>{}</td><tr>
<tr><td>DBI3  {}  FWVER {}</td><tr>
<tr><td>Run {}</td><tr>
</table>]]>'''.format(conv_M_to_mi(elapsed_dist) if spdIsMph else elapsed_dist, distStr,
                                               conv_M_to_ft(min_altitude) if altIsFt else min_altitude, altStr,
                                               conv_M_to_ft(max_altitude) if altIsFt else max_altitude, altStr,
                                               conv_M_to_mi(max_sog * 60 * 60) if spdIsMph else max_sog,
                                               conv_M_to_mi(
                                                   max_computed_sog * 60 * 60) if spdIsMph else max_computed_sog,
                                               sogStr,
                                               conv_M_to_mi(avg_sog * 60 * 60) if spdIsMph else avg_sog, sogStr,
                                               kml_start.isoformat('T'),
                                               kml_end.isoformat('T'),
                                               self.dbi3_sn, dbi3_fwver,
                                               datetime.now().isoformat(' '))

            #
            # Moving on to KML generation

            # Create the KML document
            kml = Kml(open=1, name=kml_start.strftime('%Y%m%d_%H%MZ_Track'), description=property_table)
#            doc = kml.newdocument(name=kml_start.strftime('%Y%m%d_%H%MZ_Track'), description=property_table)
                                  # snippet=Snippet('DBI3LogConverter run ' + datetime.now().isoformat(' ')))
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
            if 'AMBT' in self.kml_fields:
                schema.newgxsimplearrayfield(name='a_temp', type=Types.float, displayname='Ambient ' + tempStr)
            if 'TOPT' in self.kml_fields:
                schema.newgxsimplearrayfield(name='t_temp', type=Types.float, displayname='Top ' + tempStr)
            if 'DIFF' in self.kml_fields:
                schema.newgxsimplearrayfield(name='d_temp', type=Types.float, displayname='Diff ' + tempStr)
            if 'COG' in self.kml_fields:
                schema.newgxsimplearrayfield(name='cog', type=Types.float, displayname='COG')
            if 'SOG' in self.kml_fields:
                schema.newgxsimplearrayfield(name='sog', type=Types.float, displayname='SOG ' + sogStr)
            if 'ROC' in self.kml_fields:
                schema.newgxsimplearrayfield(name='roc', type=Types.float, displayname='ROC ' + rocStr)
            if 'BATM' in self.kml_fields:
                schema.newgxsimplearrayfield(name='batm', type=Types.float, displayname='BAT V')
            if 'BRDT' in self.kml_fields:
                schema.newgxsimplearrayfield(name='brdt', type=Types.float, displayname='BRD ' + tempStr)

            # Create a new track in the folder
            trk = fol.newgxtrack(name=kml_start.strftime('DBI3 %Y%m%d_%H%MZ'),
                                 altitudemode=self.altitudemode,  # absolute, clampToGround, relativeToGround
                                 extrude=self.extend_to_ground,
                                 description=property_table)
            trk.lookat.gxtimespan.begin = kml_start.isoformat('T')
            trk.lookat.gxtimespan.end = kml_end.isoformat('T')
            trk.lookat.longitude = max_lon - ((max_lon - min_lon) / 2)
            trk.lookat.latitude = max_lat - ((max_lat - min_lat) / 2)
            trk.lookat.range = calc_distance((min_lat, min_lon), (max_lat, max_lon)) * 1.5

            # Apply the above schema to this track
            trk.extendeddata.schemadata.schemaurl = schema.id

            # Add all the information to the track
            trk.newwhen(kml_when)  # Each item in the give nlist will become a new <when> tag
            trk.newgxcoord(kml_coord)
            pnt = fol.newpoint(name='Start', coords=[(kml_start_lon, kml_start_lat)])
            pnt.style.labelstyle.color = kml_start_color
            pnt.style.iconstyle.icon.href = 'http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png'
            pnt = fol.newpoint(name='Finish', coords=[(kml_end_lon, kml_end_lat)])
            pnt.style.labelstyle.color = kml_end_color
            pnt.style.iconstyle.icon.href = 'http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png'

            if 'AMBT' in self.kml_fields:
                trk.extendeddata.schemadata.newgxsimplearraydata('a_temp', kml_a_temp)
            if 'TOPT' in self.kml_fields:
                trk.extendeddata.schemadata.newgxsimplearraydata('t_temp', kml_t_temp)
            if 'DIFF' in self.kml_fields:
                trk.extendeddata.schemadata.newgxsimplearraydata('d_temp', kml_diff_t)
            if 'COG' in self.kml_fields:
                trk.extendeddata.schemadata.newgxsimplearraydata('cog', kml_cog)
            if 'SOG' in self.kml_fields:
                trk.extendeddata.schemadata.newgxsimplearraydata('sog', kml_sog)
            if 'ROC' in self.kml_fields:
                trk.extendeddata.schemadata.newgxsimplearraydata('roc', kml_roc)
            if 'BATM' in self.kml_fields:
                trk.extendeddata.schemadata.newgxsimplearraydata('batm', kml_batm)
            if 'BRDT' in self.kml_fields:
                trk.extendeddata.schemadata.newgxsimplearraydata('brdt', kml_brdt)

            # Styling
            trk.stylemap.normalstyle.iconstyle.icon.href = 'http://earth.google.com/images/kml-icons/track-directional/track-0.png'
            trk.stylemap.normalstyle.linestyle.color = kml_line_color
            trk.stylemap.normalstyle.linestyle.width = 3
            trk.stylemap.highlightstyle.iconstyle.icon.href = 'http://earth.google.com/images/kml-icons/track-directional/track-0.png'
            trk.stylemap.highlightstyle.iconstyle.scale = 1.2
            trk.stylemap.highlightstyle.linestyle.color = kml_line_color
            trk.stylemap.highlightstyle.linestyle.width = 8

            # Save the kml to file
            kml.save(base_name + ".kml")

            return 0, proc_log

    def kml_summary(self):
        """Read and parse a log file to build summary information.

        Returns:
        """

        # Determine unit conversion for additional data fields
        # Allow additional data fields to be english or metric
        if not self.kml_use_metric:
            tempIsF = True     # False=centegrade
            altIsFt = True     # False=meters
            spdIsMph = True    # False=kph
            varioIsFpm = True  # False=meters per second
        else:
            tempIsF = False
            varioIsFpm = False
            spdIsMph = False
            altIsFt = False

        debug = False

        log_state = 1  # 1=expecting start line, 2=records
        header_line = False
        tot_recs = 0
        dat_recs = 0
        trim_recs = 0
        bad_recs = 0
        # Monitor min/max track data to calculate a bounding box
        min_lon = 180.0
        max_lon = -180.0
        min_lat = 90.0
        max_lat = -90.0
        min_toptF = 100.0  # when TOPT is missing, we display this default data
        min_toptC = 40.0  # - or this

        # "Trip Computer" fields.  Summary fields of a given track.
        elapsed_dist = 0.0  # summation of Meters between pairs of points
        max_sog = None  # Max SOG in M/s seen
        max_computed_sog = None
        min_altitude = None  # Max ALT in Meters
        max_altitude = None  # Min ALT in Meters

        # initialize data lists to construct the KML output
        kml_start = None  # datetime of the first GPS data line
        kml_end = None  # datetime of the last GPS data line
        kml_when = []
        kml_coord = []
        kml_a_temp = []
        kml_t_temp = []
        kml_diff_t = []
        kml_cog = []
        kml_sog = []
        kml_roc = []
        kml_batm = []
        kml_brdt = []

        proc_log = ''  # Accumulate print output from the entire conversion

        with open(self.filename) as myfile:
            rec_time = None
            # calculate elapsed distance by summing distance between last and current point
            last_lat = None
            last_lon = None
            for line in myfile:
                tot_recs += 1
                logvars = {}
                try:
                    line = line.rstrip('\r\n')
                    arg_pairs = line.split(" ")
                    for p in arg_pairs:  # type: str
                        var, val = p.split("=")  # type: (str, str)
                        logvars[var] = val
                except Exception as e:
                    print 'Exception parsing line {} is: {}'.format(line, e)
                    bad_recs += 1
                    continue

                if 'DATE' in logvars.keys():
                    # datetime from a start or end line
                    log_datetime = datetime.strptime(logvars['DATE'] + ' ' + logvars['TIME'], '%Y-%m-%d %H:%M:%S')
                else:
                    log_datetime = None

                if log_state == 1:  # Expecting the start line from the log file
                    missing_key = self.__field_check(start_fields, logvars)
                    if missing_key is not None:
                        print 'Start record missing field ' + missing_key
                        break
                    start_datetime = log_datetime
                    rec_time = log_datetime  # first data record timestamp is start
                    dbi3_fwver = logvars['FWVER']
                    if self.dbi3_sn is None:
                       self.dbi3_sn = logvars['SN']
                    log_state = 2
                    proc_log += '  Start time ' + start_datetime.isoformat(' ')
                elif log_state > 1 and log_datetime is not None:
                    # START record was processed, the next record with a DATE is the END record
                    end_datetime = log_datetime
                    missing_key = self.__field_check(end_fields, logvars)
                    if missing_key is None:
                        log_state = 3
                        proc_log += '\n  Total records={}  data records={}  bad records={}'.format(tot_recs,
                                                                                                   dat_recs, bad_recs)
                        proc_log += '\n  End time ' + end_datetime.isoformat('T') + ' Rec time ' + \
                            rec_time.isoformat('T')
                    else:
                        print 'End record missing field ' + missing_key
                    break
                else:
                    # This should be a DATA record
                    missing_key = self.__field_check(data_fields, logvars)
                    if missing_key is None:
                        if logvars['GPSS'] == '0':
                            ####
                            # This is a data record and it has GPS data
                            ####
                            # TODO if trim_start is defined and rec_time < trim_start
                            #  or  trim_end is defined and rec_time > trim_end,
                            #      count as trim_recs and skip to the next record
                            if self.trim_start_time is not None and rec_time < self.trim_start_time:
                                trim_recs += 1
                                continue
                            elif self.trim_end_time is not None and rec_time > self.trim_end_time:
                                trim_recs += 1
                                continue

                            dat_recs += 1
                            if debug:
                                print 'Record ' + rec_time.isoformat('T') + ' ' + logvars['LAT'] + ' ' + logvars['LONG']

                            # calculate and accumulate KML data
                            kml_lat = self.__ddmm2d(logvars['LAT'])
                            kml_lon = self.__ddmm2d(logvars['LONG'])
                            # calculate min/max lat and lon so we can construct a display bounding box
                            if kml_lat < min_lat:
                                min_lat = kml_lat
                            if kml_lat > max_lat:
                                max_lat = kml_lat
                            if kml_lon < min_lon:
                                min_lon = kml_lon
                            if kml_lon > max_lon:
                                max_lon = kml_lon
                            # Append the time and coordinate lists
                            altitude = float(logvars['ALT'])
                            if self.altitude_offset is not None: altitude += self.altitude_offset

                            #
                            # For trip stats, sum the total distance traveled, max speed, min/max altitude
                            #
                            if last_lat is not None:
                                point_dist = calc_distance((last_lat, last_lon), (kml_lat, kml_lon))
                                elapsed_dist += point_dist
                                computed_sog = point_dist / 2.0  # fixed time between point is 2 seconds
                                if max_computed_sog is None or computed_sog > max_computed_sog:
                                    max_computed_sog = computed_sog
                            last_lat = kml_lat  # save last lat/lon for the next time thru the loop
                            last_lon = kml_lon
                            if max_altitude is None or altitude > max_altitude:
                                max_altitude = altitude
                            if min_altitude is None or altitude < min_altitude:
                                min_altitude = altitude
                            sog = float(logvars['SOG'])
                            if max_sog is None or sog > max_sog:
                                max_sog = sog

                            #
                            # Additional data fields
                            #
                            amb_temp = conv_C_to_F(float(logvars['AMBT'])) if tempIsF else float(logvars['AMBT'])
                            if logvars['TOPTS'] == '1':
                                top_temp = conv_C_to_F(float(logvars['TOPT'])) if tempIsF else float(logvars['TOPT'])
                            else:
                                top_temp = min_toptF if tempIsF else min_toptC
                            sog = float(logvars['SOG'])
                            sog = conv_M_to_mi(sog * 60 * 60) if spdIsMph else sog
                            roc = float(logvars['ROC'])
                            roc = conv_M_to_ft(roc * 60) if varioIsFpm else roc
                            brdt = float(logvars['BRDT'])
                            brdt = conv_C_to_F(brdt) if tempIsF else brdt
                            # Finished a valid data record, capture the first time as kml_start,
                            # update kml_end on each valid data record so we have the last time.
                            if kml_start is None:
                                kml_start = rec_time
                            kml_end = rec_time
                    else:
                        print 'Data record missing field ' + missing_key
                        bad_recs += 1
                    # Do we increment the time before or after the data records?
                    rec_time += two_seconds

            rtn_val = dat_recs
            if log_state != 3:
                rtn_val = -1

            return SummaryList(status = rtn_val,
                               gps_start = kml_start,
                               gps_end = kml_end,
                               min_altitude = min_altitude,
                               max_altitude = max_altitude)


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
            if not r_key in myvars:
                return r_key
        return None

    @staticmethod
    def __ddmm2d(dm):
        """Convert DBI3 ddmm.mmmmi to floating point dd.ddd

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

    Constructs a list of available log conversions, defaults the select to new files only.

    New files can either be any log that doesn't have a current KML, or only logs later than
    the current latest KML.  Default is the later.

    Allows editing of the selections.  The list can then be used to drive multiple conversions.
    """

    def __init__(self, log_path, dbi3_sn, kml_path, age_limit=None, verbose=False):
        """

        :param str log_path:  File system path to the DBI3 log files
        :param str kml_path:  File system path to the DBI3 KML files
        :param datetime age_limit: optional age limit, log files older are not considered for conversion
        :param bool verbose:  enable verbose program flow messages
        """
        self.log_path = log_path
        self.dbi3_sn = dbi3_sn
        self.kml_path = kml_path
        self.age_limit = age_limit
        self.conversion_list = []
        self.verbose = verbose
        self.debug = False
        self.new_limit = None
        # The determine "new" KML we need to know the latest KML in kml_path
        dt = None
        for item in sorted(os.listdir(self.kml_path), reverse=True):
            if not os.path.isfile(os.path.join(self.kml_path, item)):
                continue
            try:
                dt = datetime.strptime(item, "%Y%m%d_%H%M_{}.kml".format(dbi3_sn))
            except ValueError as e:
                if self.debug:
                    print('Parse error of {}:{}'.format(item, e.message))
            if dt is not None:
                self.new_limit = dt.replace(tzinfo=utc) + timedelta(minutes=1)  # make new_limit timezone aware
                if self.verbose:
                    print 'DBI3 new KML file threshold: {}'.format(self.new_limit)
                break

    def refresh_list(self, new_logs_only=False):
        """Builds list of available LOG files and selects those without a corresponding KML conversion.

        For each DBI3 log file, if the corresponding kml file does not exists,
        run the conversion.

        :return list,ConversionList:
        """
        dt_limit = None
        if new_logs_only and self.new_limit is not None:
            dt_limit = self.new_limit
        elif self.age_limit is not None:
            dt_limit = self.age_limit

        self.conversion_list = []
        # If we have an age limit, construct a matching filename for comparison
        age_limit_name = None
        if dt_limit is not None:
            age_limit_name = dt_limit.strftime('%Y_%m_%d_%H_%M_%S.log')

        prog = re.compile('^(\d{4})_(\d\d)_(\d\d)_(\d\d)_(\d\d)_(\d\d).log$')
        for item in sorted(os.listdir(self.log_path)):
            match = prog.match(item)
            log_filename = os.path.join(self.log_path, item)
            if match and os.path.isfile(log_filename) and (age_limit_name is None or item > age_limit_name):
                # item matches the re, is a file, and exceeds the age limit if defined
                selected = False
                data = None
                kml_name = match.expand('\\1\\2\\3_\\4\\5_') + self.dbi3_sn
                kml_filename = os.path.join(self.kml_path, kml_name)
                log_metaname = os.path.join(self.log_path, '.' + item[0:-4])
                if not os.path.isfile(kml_filename + '.kml'):
                    selected = True
                if os.path.isfile(log_metaname):
                    # meta file data to override some conversion settings
                    with open(log_metaname, 'r') as meta:
                        data = json.load(meta)
                self.conversion_list.append(ConversionList(log_name=item,
                                                           log_filename=log_filename,
                                                           kml_name=kml_name,
                                                           kml_filename=kml_filename,
                                                           new_file=selected,
                                                           meta_name=log_metaname,
                                                           override=data))

        return self.conversion_list
