# vim: set shiftwidth=4 softtabstop=4 autoindent expandtab:
###########################################################################
# Copyright (C) Aerostation/Ronald Thornton 2020
# All rights reserved.
###########################################################################
"""Application and Conversion configuration option objects"""

from __future__ import print_function

import os
import sys
from datetime import datetime
import json
import collections
from serial.tools.list_ports import comports

try:  # Handle either python 2/3 import syntax
    from dbi3_common import utc, DBI_ALL_LOG_FIELDS, DBI_DEFAULT_LOG_FIELDS, DBI_CONF_FILE, \
        DEF_LOG_PATH, DEF_KML_PATH
except ImportError:
    from .dbi3_common import utc, DBI_ALL_LOG_FIELDS, DBI_DEFAULT_LOG_FIELDS, DBI_CONF_FILE, \
        DEF_LOG_PATH, DEF_KML_PATH
try:  # Handle input for python 2/3
    input = raw_input
except NameError:
    pass

# Application config file alters default operation.  The available keys are
DBI3_APPLICATION_CONFIG_ATTR = [
    'log_path',
    'kml_path',
    'com_port',
    'altitudemode',
    'extend_to_ground',
    'kml_fields',
    'kml_use_metric',
    'age_limit',
    'filter_new',
    'filter_invalid',
    'verbose',
]

# Metadata log config files can alter the converted output of individual logs.  The available keys are
METADATA_CONFIG_ATTR = [
    "altitudemode",
    "altitude_offset",
    "extend_to_ground",
    "kml_use_metric",
    "kml_fields",
    "trim_start_time",
    "trim_end_time",
    "track_note",
]

'''namedtuple for the config file editor
        field_name = the actual config file field name
        name = may be a more user friendly paramater name
        default = default value
        validation_function = function to validate value
        direct = True if the validation function does its own prompting (for complex/dynamic prompts)
        help_txt = help
'''
ConfigSpec = collections.namedtuple('ConfigSpec', 'field_name name default validation_func direct help_txt')


class Dbi3ConfigOptions:
    """Initialize and maintain application config settings.

    Methods to edit the config files for both Application and KML config options.
    """

    def __init__(self, sn=None,
                 prefer_gps=None,
                 altitudemode=None, altitude_offset=None,
                 extend_to_ground=None, verbose=None,
                 fields_choice=None,
                 kml_use_metric=None,
                 age_limit=None):

        self.conf_file = DBI_CONF_FILE

        #############
        # Application level CONFIG items, persisted in DBI_CONF_FILE
        #############
        self.log_path = None
        self.kml_path = None
        self.com_port = None
        self.prefer_gps = True  # prefer GPS over pressure altitude if available
        self.altitudemode = "absolute"
        self.extend_to_ground = True
        self.kml_fields = DBI_DEFAULT_LOG_FIELDS
        self.kml_use_metric = False
        self.age_limit = None  # in days.  When age filter enabled, imit log/kml list outputs to newer
        self.filter_new = True
        self.filter_invalid = True
        self.verbose = False
        #############
        # Run time config, the SN read from a connected DBI3
        self.sn = None
        # log/kml list filter options
        self.CLI_new_logs = True  # only list new files
        self.CLI_skip_invalid = True  # don't list invalid files (bad record counts)
        self.CLI_age_limit = None  # datetime of the age_limit for log/track list outputs

        # Update default configs from the config file
        self._update_config_from_file()

        # Now apply any command line override
        if sn is not None: self.sn = sn
        if altitudemode is not None: self.altitudemode = altitudemode
        if prefer_gps is not None: self.prefer_gps = prefer_gps
        if extend_to_ground is not None: self.extend_to_ground = extend_to_ground
        if fields_choice is not None: self.kml_fields = fields_choice
        if kml_use_metric is not None: self.kml_use_metric = kml_use_metric
        if age_limit is not None: self.age_limit = age_limit
        if verbose is not None: self.verbose = verbose

    def update_dbi3_sn(self, sn):
        """The SN we are working with can change during execution so we provide an update method"""
        self.sn = sn

    def _update_config_from_file(self):
        if os.path.isfile(self.conf_file):
            with open(self.conf_file, 'r') as conf_file:
                data = json.load(conf_file)
                print('DBI3 config file: {}'.format(self.conf_file))
            # For all defined config attributes, if it exists in the file, update our variable
            for field in DBI3_APPLICATION_CONFIG_ATTR:
                if field in data:
                    setattr(self, field, data[field])

    def edit_config(self):
        print('''
    log_path and kml_path must be properly configured before
      the application can run.  Changing the paths will not move
      any existing files.
    com_port can be left as default (None) and logs download
      will attempt to find the correct port.
    Other parameters can be left as default.
    ''')
        data = {}
        if os.path.isfile(self.conf_file):
            with open(self.conf_file, 'r') as conf_file:
                data = json.load(conf_file)
        print('CONFIG-{}'.format(json.dumps(data)))
        AppConfig = [
            ConfigSpec('log_path', 'log_path', DEF_LOG_PATH, self.path_check, False,
                       'Directory path to store DBI3 log files.'),
            ConfigSpec('kml_path', 'kml_path', DEF_KML_PATH, self.path_check, False,
                       'Directory path to store DBI3 log files.'),
            ConfigSpec('com_port', 'com_port', None, self.ask_for_port, True, 'Serial port connected to the DBI3'),
            ConfigSpec('age_limit', 'filter_age_limit', None, self.int_check, False,
                       'Filter Log/KML lists to files less than filter_age_limit days ago'),
            ConfigSpec('filter_new', 'filter_new', True, self.true_false, False,
                       'Filter Log/KML lists to files newer than any on the PC? T/F'),
            ConfigSpec('filter_invalid', 'filter_invalid', True, self.true_false, False,
                       'Filter Log/KML lists to skip invalid (no GPS data logs? T/F'),
            ConfigSpec('prefer_gps', 'prefer_gps', True, self.true_false, False,
                       'Prefer GPS altitude in track points if available. T/F'),
            ConfigSpec('altitudemode', 'altitudemode', 'absolute', self.alt_mode_check, False,
                       'Default Google Earth altitude display = absolute, clampToGround, relativeToGround'),
            ConfigSpec('extend_to_ground', 'extend_to_ground', True, self.true_false, False,
                       'Default Google Earth extend_to_ground setting? T/F'),
            ConfigSpec('kml_use_metric', 'kml_use_metric', False, self.true_false, False,
                       'Default Google Earth use Metric values for KML data? T/F'),
            ConfigSpec('kml_fields', 'kml_fields', ','.join(DBI_DEFAULT_LOG_FIELDS), self.fields_check, False,
                       'Default Google Earth extra data fields, available (ALL,{})'.format(','.join(DBI_ALL_LOG_FIELDS))),
            ConfigSpec('verbose', 'verbose', False, self.true_false, False, 'Enable verbose debug output? T/F')
        ]

        self._update_config_file(self.conf_file, AppConfig, data)

    def edit_conversion_config(self, cfg_path):
        data = {}
        if os.path.isfile(cfg_path):
            with open(cfg_path, 'r') as conf_file:
                data = json.load(conf_file)

        KmlConfig = [
            ConfigSpec('track_note', 'track_note', None, self.text_check, False,
                       'Single line text added to track properties block (e.g. passenger names)'),
            ConfigSpec('trim_start_time', 'trim_start_time', None, self.time_check, False,
                       'Ignore DBI3 data until YYYYMMDDhhmmss'),
            ConfigSpec('trim_end_time', 'trim_end_time', None, self.time_check, False, 'Ignore DBI3 data after YYYYMMDDhhmmss'),
            ConfigSpec('prefer_gps', 'prefer_gps', True, self.true_false, False,
                       'Prefer GPS altitude in track points if available. T/F'),
            ConfigSpec('altitudemode', 'altitudemode', None, self.alt_mode_check, False,
                       'Google Earth altitude display = absolute, clampToGround, relativeToGround'),
            ConfigSpec('altitude_offset', 'altitude_offset', None, self.float_check, False,
                       'floating point offset in meters to the DBI3 reported altitude'),
            ConfigSpec('extend_to_ground', 'extend_to_ground', True, self.true_false, False,
                       'Should Google Earth extend tracks to the ground? T/F'),
            ConfigSpec('kml_use_metric', 'kml_use_metric', False, self.true_false, False,
                       'Use metric instead of english measure for extra data? T/F'),
            ConfigSpec('kml_fields', 'kml_fields', ','.join(DBI_DEFAULT_LOG_FIELDS), self.fields_check, False,
                       'Google Earth extra data fields, available (ALL,{})'.format(','.join(DBI_ALL_LOG_FIELDS)))
        ]

        self._update_config_file(cfg_path, KmlConfig, data)

    def _update_config_file(self, cfg_path, config_table, data):
        while True:
            # Display the current config values.
            print('   {:<24} {:<12}: {}'.format('field', '(default)', '  current_value'))
            print('================================================================')
            for cfg_index, el in enumerate(config_table, 1):
                k = data.get(el.field_name)
                l = getattr(self, el.field_name, None)
                current_val = k if k is not None else 'APP->{}'.format(l) if l is not None else None
                print('{:2} {:<24} {:<12}:  {}'.format(cfg_index, el.name, '({})'.format(el.default), current_val))
            print('')
            new_val = input('(s)ave, (q)uit without save, or line # to edit: ').lower()
            if new_val.startswith('s'):
                # If the cfg file already exists, move it to a backup name
                if os.path.isfile(cfg_path):
                    # if a backup file already exists, remove it.
                    if os.path.isfile(cfg_path + '~'):
                        os.remove(cfg_path + '~')
                    os.rename(cfg_path, cfg_path + '~')
                with open(cfg_path, 'w') as conf_file:
                    json.dump(data, conf_file, indent=4, separators=(',', ': '), sort_keys=True)
                    conf_file.write('\n')
                break
            elif new_val.startswith('q') or new_val == '':
                # quit on 'q' or empty line
                break
            else:
                # assume it's an integer and try to convert
                try:
                    idx = int(new_val) - 1  # adjust to list index
                    if idx < 0:
                        print('Bad row number [{}]'.format(new_val))
                        continue
                    el = config_table[idx]
                except ValueError:
                    print('Unknown command [{}]\n'.format(new_val))
                    continue
                except Exception as e:
                    print('Can not edit line [{}]: {}\n'.format(new_val, e))
                    continue

            while True:  # loop on field update until complete or we quit
                k = data.get(el.field_name)
                l = getattr(self, el.field_name, None)
                current_val = k if k is not None else 'APP->{}'.format(l) if l is not None else None
                print('{:2} {:<24} {:<12}:  {}'.format(cfg_index, el.name, '({})'.format(el.default), current_val))
                if not el.direct:
                    # We do standard prompting before calling validation
                    new_val = input('New value (?=help): ')
                    if new_val == '':
                        # Keep current value
                        pass
                    elif new_val == '*':
                        # value is None - remove the field from the config data
                        data.pop(el.field_name, None)
                    elif new_val == '.':
                        # Set value to default
                        if el.default is None:
                            # remove the field from the config data
                            data.pop(el.field_name, None)
                        else:
                            data[el.field_name] = el.default
                    elif new_val == '?':
                        # Config field help
                        print('\nHINT- {}'.format(el.help_txt))
                        print('      cr=keep current, "*"=None, "."=default')
                        continue
                    else:
                        # Pass new value to validation method
                        new_val = el.validation_func(el.name, new_val)
                        if new_val is not None:
                            data[el.field_name] = new_val
                        else:
                            # Failed validation, loop
                            continue
                else:
                    # The validation routine does its own prompt
                    new_val = el.validation_func(el.name, data.get(el.field_name, el.default))
                    if new_val is not None:
                        data[el.field_name] = new_val
                    else:
                        # remove the field
                        data.pop(el.field_name, None)

                break

    #
    # Configuration file field validation methods follow
    #
    # All validation methos receive two parameters and return the value or None
    #
    @staticmethod
    def text_check(param_name, line):
        """text_check input validation is a nop for now"""
        return line


    @staticmethod
    def int_check(param_name, var):
        """Verify the text is numeric and return the int value (or None)"""
        try:
            return int(var)
        except Exception as e:
            print("Exception converting {} [{}] to integer".format(param_name, var))
        return None


    @classmethod
    def path_check(cls, param_name, new_path):
        if new_path.startswith('~/'):
            # Handle HOME directory expansion
            new_path = os.path.join(os.path.expanduser('~'), new_path[2:])
        if not os.path.isdir(new_path):
            print("{} path {} does not exist.".format(param_name, new_path))
            new_val = input('Should I create the path (y/n)? ')
            if new_val.startswith('y'):
                return new_path if cls.__verify_log_path(new_path) else None
            return None
        return new_path


    @staticmethod
    def true_false(param_name, selection):
        """This will take ANY input and return True or False.  Anything that doesn't look True becomes False!"""
        s = selection.lower()
        if s.startswith('t') or s.startswith('y') or s.startswith('on') or s == '1':
            return True
        return False


    @staticmethod
    def alt_mode_check(param_name, mode):
        valid_modes = ['absolute', 'clampToGround', 'relativeToGround']
        if mode in valid_modes:
            return mode
        return None


    @staticmethod
    def float_check(param_name, fp_string):
        return float(fp_string)


    @staticmethod
    def time_check(param_name, time_str):
        return datetime.strptime(time_str, "%Y%m%d%H%M%S").strftime("%Y%m%d%H%M%S")


    @staticmethod
    def ask_for_port(param_name, com_port):
        """
        Show a list of ports and ask the user for a choice. To make selection
        easier on systems with long device names, also allow the input of an
        index.
        """
        sys.stderr.write('\n--- Available ports:\n')
        ports = []
        for n, (port, desc, hwid) in enumerate(sorted(comports(include_links=True)), 1):
            print(' {:2}: {:20} {}\n        [{}]'.format(n, port, desc, hwid))
            ports.append(port)
        while True:
            port = input('- Enter port index, full name, cr=keep current, "."=set default: ')
            if port == '':
                return com_port
            elif port == '.':
                return None
            try:
                index = int(port) - 1
                if not 0 <= index < len(ports):
                    sys.stderr.write('--- Invalid index!\n')
                    continue
            except ValueError:
                pass
            else:
                port = ports[index]
            return port


    @staticmethod
    def fields_check(param_name, fields):
        """Check comma separated list of KML data fields."""
        fl = fields.split(',')
        # Verifiy the fields list and set the field names in a boolean dictionary
        if 'ALL' in fl:
            # Special case, turns on all fields
            return DBI_ALL_LOG_FIELDS
        for fn in fl:
            if fn not in DBI_ALL_LOG_FIELDS:
                print('error: argument --fields: invalid choice: "{}" is not in "{}"'.format(fn, DBI_ALL_LOG_FIELDS))
                return None
        return fl

    @staticmethod
    def __verify_log_path(a_path):
        """Verify a directory path exists or attempt to create the leaf"""
        try:
            os.mkdir(a_path)
        except OSError:
            if not os.path.isdir(a_path):
                return False
        return True

    def non_interactive_auto_config(self):
        """For first time users, we attempt to auto configure the log and KML destinations."""
        if not self.__verify_log_path(DEF_LOG_PATH):
            print('Can not initialize log path {}'.format(DEF_LOG_PATH))
            return False
        self.log_path = DEF_LOG_PATH
        if not self.__verify_log_path(DEF_KML_PATH):
            print('Can not initialize KML path {}'.format(DEF_KML_PATH))
            return False
        self.kml_path = DEF_KML_PATH
        data = {'log_path': self.log_path, 'kml_path': self.kml_path}
        with open(DBI_CONF_FILE, 'w') as conf_file:
            json.dump(data, conf_file, indent=4, separators=(',', ': '), sort_keys=True)
            conf_file.write('\n')
        print('Created config file {}'.format(DBI_CONF_FILE))
        return True


class Dbi3ConversionOptions:
    """Dbi3 conversion config settings.

    Set default values,
    overrides with optional constructor parameters,
    overrides with optional metadata config file.
    In that order.
    """

    def __init__(self, filename, app_config, altitude_offset=None):
        """

        :param str filename: The full path to the log file, used to compute metadata filename
        :param Dbi3ConfigOptions app_config:
        :param float altitude_offset: optional command line argument to offset pressure altitude
        """

        # Establish config defaults
        self.log_filename = filename
        self.altitudemode = app_config.altitudemode
        self.altitude_offset = altitude_offset  # floating point
        self.extend_to_ground = app_config.extend_to_ground
        self.kml_fields = app_config.kml_fields
        self.kml_use_metric = app_config.kml_use_metric
        self.prefer_gps = app_config.prefer_gps  # True=prefer GPS altitude if available
        self.verbose = app_config.verbose
        self.trim_start_time = None  # config file is string, this is datetime
        self.trim_end_time = None  # config file is string, this is datetime
        self.track_note = None

        # Optional override config from a metadata config file
        self.log_meta = os.path.join(os.path.dirname(filename), '.' + os.path.splitext(os.path.basename(filename))[0])
        if os.path.isfile(self.log_meta):
            # This log file has persisted meta data, get the config options
            with open(self.log_meta, 'r') as meta:
                data = json.load(meta)
            # For all defined config attributes, if it exists in the file, update our variable
            for field in METADATA_CONFIG_ATTR:
                if field in data:
                    setattr(self, field, data[field])
            # the trim fields need to be converted to datetime.
            if self.trim_start_time is not None:
                self.trim_start_time = datetime.strptime(self.trim_start_time, "%Y%m%d%H%M%S")
            if self.trim_end_time is not None:
                self.trim_end_time = datetime.strptime(self.trim_end_time, "%Y%m%d%H%M%S")

    def __str__(self):
        return 'log_filename:{} altitudemode:{} altitude_offset:{} extend_to_ground:{} kml_fields:{}'\
               ' kml_use_metric:{} prefer_gps:{} verbose:{} trim_start_time:{} trim_end_time:{} track_note:{}'.format(
            self.log_filename,
            self.altitudemode,
            self.altitude_offset,
            self.extend_to_ground,
            self.kml_fields,
            self.kml_use_metric,
            self.prefer_gps,
            self.verbose,
            self.trim_start_time,
            self.trim_end_time,
            self.track_note)
