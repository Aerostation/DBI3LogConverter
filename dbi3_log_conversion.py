#!/usr/bin/env python
# vim: set sw=4 st=4 ai expandtab:
"""Program to convert DBI3 log files to KML"""

import os
import sys
import json
from datetime import datetime
from datetime import timedelta
from simplekml import Kml, Snippet, Types
import math

two_seconds = timedelta(seconds=2)  # time increment between data records
kml_line_color = 'ff0000ff'  # hex aabbggrr

# Required start record fields - to validate log record content
start_fields = ['FWVER', 'SN', 'DATE', 'TIME']
data_fields = ['ALT', 'ROC', 'AMBT', 'GPSS', 'SOG', 'COG', 'LONG', 'LAT', 'TOPTS', 'TOPT', 'BATM', 'BRDT']
end_fields = ['DATE', 'TIME']
def_fields = ['ROC', 'TOPT', 'AMBT', 'DIFF', 'SOG', 'COG', 'BATM', 'BRDT']


class Dbi3LogConversion:
    config_attr = ["altitudemode",
                   "altitude_offset",
                   "extend_to_ground",
                   "fields_choice",
                   "kml_use_metric"]
    kml_do_fields = {}

    def __init__(self, filename,
                 altitudemode=None, altitude_offset=None,
                 extend_to_ground=None, verbose=None,
                 fields_choice=None,
                 kml_use_metric=None):

        self.filename = filename

        # Establish config defaults
        self.altitudemode = "absolute"
        self.altitude_offset = None  # floating point
        self.extend_to_ground = True
        self.fields_choice = def_fields
        self.kml_use_metric = False
        self.verbose = False

        # Override defaults with optional parameters
        if altitudemode is not None: self.altitudemode = altitudemode
        if altitude_offset is not None: self.altitude_offset = altitude_offset
        if extend_to_ground is not None: self.extend_to_ground = extend_to_ground
        if fields_choice is not None: self.fields_choice = fields_choice
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
            print 'RDT override conversion with meta {}'.format(data)
            for fld in self.config_attr:
                if fld in data: setattr(self, fld, data[fld])


    def kml_convert(self, base_name):

#def dbi3_log_conversion(filename, csv_file, base_name,
#                        altitudemode="absolute", altitude_offset=0.0, verbose=False,
#                        fields_choice = ['ROC', 'TOPT', 'AMBT', 'DIFF', 'SOG', 'COG', 'BATM', 'BRDT'],
#                        kml_use_metric=False):
        """Function to read and convert a DBI3 log file to XML (or other) format

        Args:
            filename:  The DBI3 log file path
            csv_file:  Optional csv_file, may be None
            base_name: Base path and filename for output - add extension

        Returns:
            null

        """

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
        bad_recs = 0
        # Monitor min/max track data to calculate a bounding box
        min_lon = 180.0
        max_lon = -180.0
        min_lat = 90.0
        max_lat = -90.0
        min_toptF = 100.0  # when TOPT is missing, we display this default data
        min_toptC = 40.0   # - or this

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

        proc_log = ''

        with open(self.filename) as myfile:
            start_datetime = None
            end_datetime = None
            rec_time = None
            for line in myfile:
                tot_recs += 1
                myvars = {}
                try:
                    line = line.rstrip('\r\n')
                    arg_pairs = line.split(" ")
                    for p in arg_pairs:  # type: str
                        var, val = p.split("=")  # type: (str, str)
                        myvars[var] = val
                except Exception as e:
                    print 'Exception parsing line {} is: {}'.format(line, e)
                    bad_recs += 1
                    continue

                if 'DATE' in myvars.keys():
                    # datetime from a start or end line
                    end_datetime = datetime.strptime(myvars['DATE']+' '+myvars['TIME'], '%Y-%m-%d %H:%M:%S')
                if log_state == 1:  # Expecting the start line from the log file
                    m_key = field_check(start_fields, myvars)
                    if m_key is not None:
                        print 'Start record missing field ' + m_key
                        break
                    start_datetime = end_datetime
                    rec_time = start_datetime  # first data record timestamp is start
                    dbi3_fwver = myvars['FWVER']
                    dbi3_sn = myvars['SN']
                    log_state = 2
                    proc_log += '  Start time ' + start_datetime.isoformat(' ')
                else:
                    # START record was processed, looking for DATA or STOP records
                    if 'DATE' in myvars.keys():
                        # The presence of a DATE field indicates this is a STOP record
                        m_key = field_check(end_fields, myvars)
                        if m_key is None:
                            proc_log += '\n  Total records={}  data records={}  bad records={}'.format(tot_recs,
                                                                                              dat_recs, bad_recs)
                            proc_log += '\n  End time ' + end_datetime.isoformat('T') + ' Rec time ' + rec_time.isoformat('T')
                        else:
                            print 'End record missing field ' + m_key
                        break
                    else:
                        # Not a STOP record so this must be a DATA record
                        m_key = field_check(data_fields, myvars)
                        if m_key is None:
                            if myvars['GPSS'] == '0':
                                ####
                                # This is a data record and it has GPS data
                                ####
                                dat_recs = dat_recs+1
                                if not header_line:
                                    if csv_file is not None:
                                        print >>csv_file, 'utc_d,utc_t,alt,lat,lon,head,speed,temp'
                                    header_line = True
                                if csv_file is not None:
                                    print >>csv_file, rec_time.strftime('%Y/%m/%d,%H:%M:%S,') + myvars['ALT'] + \
                                        ',' + myvars['LAT'] + ',' + myvars['LONG'] + \
                                        ',' + myvars['COG'] + ',' + myvars['SOG'] + \
                                        ',' + myvars['AMBT']
                                if debug:
                                    print 'Record ' + rec_time.isoformat('T') + ' ' + myvars['LAT'] + ' ' + myvars['LONG']

                                # calculate and accumulate KML data
                                kml_lat = ddmm2d(myvars['LAT'])
                                kml_lon = ddmm2d(myvars['LONG'])
                                if kml_lat < min_lat:
                                    min_lat = kml_lat
                                if kml_lat > max_lat:
                                    max_lat = kml_lat
                                if kml_lon < min_lon:
                                    min_lon = kml_lon
                                if kml_lon > max_lon:
                                    max_lon = kml_lon
                                kml_when.append(rec_time.isoformat('T'))
                                altitude = float(myvars['ALT'])
                                if self.altitude_offset is not None: altitude += self.altitude_offset
                                kml_coord.append((kml_lon, kml_lat, altitude))
                                #
                                # Additional data fields
                                #
                                amb_temp = C_to_F(float(myvars['AMBT'])) if tempIsF else float(myvars['AMBT'])
                                if myvars['TOPTS'] == '1':
                                    top_temp = C_to_F(float(myvars['TOPT'])) if tempIsF else float(myvars['TOPT'])
                                else:
                                    top_temp = min_toptF if tempIsF else min_toptC
                                if 'AMBT' in self.fields_choice:
                                    kml_a_temp.append(amb_temp)
                                if 'TOPT' in self.fields_choice:
                                    kml_t_temp.append(top_temp)
                                if 'DIFF' in self.fields_choice:
                                    kml_diff_t.append(top_temp-amb_temp)
                                if 'SOG' in self.fields_choice:
                                    sog = float(myvars['SOG'])
                                    sog = M_to_mi(sog * 60 * 60) if spdIsMph else sog
                                    kml_sog.append(sog)
                                if 'COG' in self.fields_choice:
                                    kml_cog.append(float(myvars['COG']))
                                if 'ROC' in self.fields_choice:
                                    roc = float(myvars['ROC'])
                                    roc = M_to_ft(roc * 60) if varioIsFpm else roc
                                    kml_roc.append(roc)
                                if 'BATM' in self.fields_choice:
                                    kml_batm.append(float(myvars['BATM']))
                                if 'BRDT' in self.fields_choice:
                                    brdt = float(myvars['BRDT'])
                                    brdt = C_to_F(brdt) if tempIsF else brdt
                                    kml_brdt.append(brdt)
                                # Finished a valid data record, capture the first time as kml_start,
                                # update kml_end on each valid data record so we have the last time.
                                if kml_start is None:
                                    kml_start = rec_time
                                kml_end = rec_time
                        else:
                            print 'Data record missing field ' + m_key
                            bad_recs += 1
                    # Do we increment the time before or after the data records?
                    rec_time += two_seconds

            if dat_recs == 0:
                print '    No GPS data records, skip KML file generations'
                return
            else:
                print proc_log

            # write the KML
            # Create the KML document
            kml = Kml(name="Tracks", open=1)
            doc = kml.newdocument(name='GPS device', snippet=Snippet('DBI3LogConverter'))
            # kml timespan is base on the first and last valid data record, not DBI3 log start/end.
            doc.lookat.gxtimespan.begin = kml_start.isoformat('T')
            doc.lookat.gxtimespan.end = kml_end.isoformat('T')
            doc.lookat.longitude = max_lon - ((max_lon - min_lon) / 2)
            doc.lookat.latitude = max_lat - ((max_lat - min_lat) / 2)
            doc.lookat.range = distance((min_lat, min_lon), (max_lat, max_lon)) * 1.5

            # Create a folder
            fol = doc.newfolder(name='Tracks')

            # Create a schema for extended data
            tempStr = 'F' if tempIsF else 'C'
            sogStr = 'MPH' if spdIsMph else 'mps'
            rocStr = 'FPM' if varioIsFpm else 'mps'
            schema = kml.newschema()
            if 'AMBT' in self.fields_choice:
                schema.newgxsimplearrayfield(name='a_temp', type=Types.float, displayname='Ambient '+tempStr)
            if 'TOPT' in self.fields_choice:
                schema.newgxsimplearrayfield(name='t_temp', type=Types.float, displayname='Top '+tempStr)
            if 'DIFF' in self.fields_choice:
                schema.newgxsimplearrayfield(name='d_temp', type=Types.float, displayname='Diff '+tempStr)
            if 'COG' in self.fields_choice:
                schema.newgxsimplearrayfield(name='cog', type=Types.float, displayname='COG')
            if 'SOG' in self.fields_choice:
                schema.newgxsimplearrayfield(name='sog', type=Types.float, displayname='SOG '+sogStr)
            if 'ROC' in self.fields_choice:
                schema.newgxsimplearrayfield(name='roc', type=Types.float, displayname='ROC '+rocStr)
            if 'BATM' in self.fields_choice:
                schema.newgxsimplearrayfield(name='batm', type=Types.float, displayname='BAT V')
            if 'BRDT' in self.fields_choice:
                schema.newgxsimplearrayfield(name='brdt', type=Types.float, displayname='BRD '+tempStr)

            # Create a new track in the folder
            trk = fol.newgxtrack(name='DBI3 ' + start_datetime.isoformat('T'),
                                 altitudemode=self.altitudemode,  # absolute, clampToGround, relativeToGround
                                 extrude=self.extend_to_ground,
                                 description='DBI3 Track  SN '+dbi3_sn+'  FWVER '+dbi3_fwver)

            # Apply the above schema to this track
            trk.extendeddata.schemadata.schemaurl = schema.id

            # Add all the information to the track
            trk.newwhen(kml_when)  # Each item in the give nlist will become a new <when> tag
            trk.newgxcoord(kml_coord)
            if 'AMBT' in self.fields_choice:
                trk.extendeddata.schemadata.newgxsimplearraydata('a_temp', kml_a_temp)
            if 'TOPT' in self.fields_choice:
                trk.extendeddata.schemadata.newgxsimplearraydata('t_temp', kml_t_temp)
            if 'DIFF' in self.fields_choice:
                trk.extendeddata.schemadata.newgxsimplearraydata('d_temp', kml_diff_t)
            if 'COG' in self.fields_choice:
                trk.extendeddata.schemadata.newgxsimplearraydata('cog', kml_cog)
            if 'SOG' in self.fields_choice:
                trk.extendeddata.schemadata.newgxsimplearraydata('sog', kml_sog)
            if 'ROC' in self.fields_choice:
                trk.extendeddata.schemadata.newgxsimplearraydata('roc', kml_roc)
            if 'BATM' in self.fields_choice:
                trk.extendeddata.schemadata.newgxsimplearraydata('batm', kml_batm)
            if 'BRDT' in self.fields_choice:
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


def ddmm2d(dm):
    '''Convert DBI3 ddmm.mmmmi to floating point dd.ddd

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
    '''
    hemi = dm[-1:]
    dm = dm[:-1]
    min_dec = dm.find('.')
    deg = dm[:min_dec-2]
    minutes = dm[min_dec-2:]
    latlon = float(deg) + float(minutes)/60.0
    if hemi == 'W' or hemi == 'S':
        latlon = 0.0 - latlon
    return latlon


def C_to_F(tempC):
    '''Convert Centigrade to Fahrenheit'''
    return 9.0/5.0 * tempC + 32


def M_to_ft(meters):
    '''Convert Meters to feet'''
    return meters * 3.28084


def ft_to_M(feet):
    '''Convert feet to Meters'''
    return feet / 3.28084


def M_to_mi(meters):
    '''Converte Meters to miles'''
    return meters * 0.000621371


def distance(origin, destination):
    '''Give distance between two points in Meters'''
    lat1, lon1 = origin
    lat2, lon2 = destination
    radius = 6371.0  # km

    dlat = math.radians(lat2-lat1)
    dlon = math.radians(lon2-lon1)
    a = math.sin(dlat/2) * math.sin(dlat/2) + math.cos(math.radians(lat1)) \
        * math.cos(math.radians(lat2)) * math.sin(dlon/2) * math.sin(dlon/2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    d = radius * c

    return d * 1000.0


def field_check(req_fields, myvars):
    '''Check that all required data fields exists

    Args:
        req_fields - list of field names
        myvars - list of parsed NAME=VALUE parsed fields

    Returns:
        None - success, no missing field
        str - the name of the first missing field detected
    '''
    for r_key in req_fields:
        if not r_key in myvars:
            return r_key
    return None
