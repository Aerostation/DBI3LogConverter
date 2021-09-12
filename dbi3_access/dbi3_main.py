#!/usr/bin/env python
# vim: set shiftwidth=4 softtabstop=4 autoindent expandtab:
###########################################################################
# Copyright (C) Aerostation/Ronald Thornton 2018-2021
# All rights reserved.
###########################################################################
"""Drive the DBI3 log downloads and conversions to KML

It can run interactively with CLI menus or --sync will run automatically to find a DBI3
serial port, download all new logs for the DBI3, then convert all new logs
to KML for that DBI3 SN.
"""
# TODO Log download and conversions to rolling journal for historical reference.  Include edits
from __future__ import print_function

import errno
import os
import argparse
import cmd
import glob
import sys
import json
from datetime import datetime, timedelta

from dbi3_access.lib.dbi3_log_conversion import Dbi3KmlList, Dbi3LogConversion
from dbi3_access.lib.dbi3_log_downloads import DBI3LogDownload
from dbi3_access.lib.dbi3_common import (
    utc,
    DBI_ALL_LOG_FIELDS,
    DBI_DEFAULT_LOG_FIELDS,
    DBI_CONF_FILE,
    DEF_LOG_PATH,
    DEF_KML_PATH,
    Spinner,
)
from dbi3_access.lib.dbi3_config_options import Dbi3ConfigOptions
from dbi3_access.lib.audit_utils import init_logger, get_log
from dbi3_access.lib.__version__ import __version__

try:  # Handle input for python 2/3
    input = raw_input
except NameError:
    pass

app_config = None  # App configuration object
# DEV temporary flag for csv
do_csv = False

# The concept of "new" files is based on the latest stored log/kml, not simply old missing files.


def convert_new_logs(app_config):
    """Convert new DBI3 logs to kml output

    For each DBI3 log file, if the corresponding kml file does not exists,
    run the conversion.

    :param Dbi3ConfigOptions app_config: Application config object
    :return: none
    """
    conv_list = Dbi3KmlList(config=app_config)
    conv_list.refresh_list()
    for le in conv_list.conversion_list:
        if le.new_file:  # only process files marked as new
            if not app_config.verbose:
                sp = Spinner()
            dbi3_obj = Dbi3LogConversion(le.log_filename, app_config)
            rtn, rtn_str = dbi3_obj.kml_convert(le.kml_filename)
            if not app_config.verbose:
                sp.stop()
            if rtn < 0:
                get_log().info(
                    "Convert FAILED {} to KML  new:{}  edits:{}   to {}\n{}".format(
                        le.log_name, "Y" if le.new_file else "N", le.override, le.kml_name, rtn_str
                    )
                )
            elif rtn > 0 and app_config.verbose:
                # not converted warning (probably no GPS data)
                get_log().info(
                    "Convert {} to KML  new:{}  edits:{}\n{}".format(
                        le.log_name, "Y" if le.new_file else "N", le.override, rtn_str
                    )
                )
            elif rtn == 0:
                get_log().info(
                    "Converted {} to KML  new:{}  edits:{}\n{}".format(
                        le.log_name, "Y" if le.new_file else "N", le.override, rtn_str
                    )
                )


def process_dbi():
    """Non-interactive DBI3 download/convert method.
    Download 'new' logs from the DBI3.  Convert 'new' downloaded logs to KML.
    'new' is defined as a log newer than what is currently on the PC.
    """
    _verify_paths()  # ensure log/kml paths exist

    down_load = None
    try:
        # log list elements contain list 'startRad26, stopRad26, start_dt, stop_dt, log_filename'
        # The log list automatically marks new logs as selected for download.
        down_load = DBI3LogDownload(app_config)
        if not app_config.verbose:
            sp = Spinner()
        log_list = down_load.get_DBI3_log_list(True)

        if log_list is not None:
            rtn = down_load.download_new_logs(log_list)
        if not app_config.verbose:
            sp.stop()
        if rtn:
            get_log().info("\n  ".join(rtn))

    except IOError as e:
        if down_load is not None and down_load.dbi3_sn is not None:
            sn = down_load.dbi3_sn
        else:
            sn = "No SN"
        com = app_config.com_port if app_config.com_port is not None else "NoPort"
        print("IO error with DBI3({}) on {}: {}".format(sn, com, e))
        print("Skip DBI3 log downloads")
        return

    # Based on the SN of the DBI3 we are connected to, adjust the log path
    app_config.update_dbi3_sn(down_load.dbi3_sn)
    convert_new_logs(app_config)


CLI_sn_list = []  # list of current DBI3 SN? log directories


def filter_text():
    """Create a display string documenting the current LOG filters."""
    fl = []
    if app_config.CLI_new_logs:
        fl.append("new_logs")
    if app_config.CLI_skip_invalid:
        fl.append("skip_invalid")
    if app_config.CLI_age_limit:
        fl.append("after-{}".format(app_config.CLI_age_limit.strftime("%Y_%m_%d_%H_%M_%S")))
    return ":".join(fl)


Cmd_exit = False  # To allow Cmd exit to bubble up from nested commands, we use this global.


class Dbi3InteractiveCommandLine(cmd.Cmd):
    """Top level Cmd menu.  Application level config and calls logs/kml sub-menus"""

    prompt = "(DBI3) "
    my_header = (
        "This is the top level menu of the DBI3 Log Download/Convert application.\n\n"
        "* This level allow configuration of the overall application and defaults used\n"
        "  to create KML output files.\n"
        '* The "logs" menu connects to the DBI3 and allows download, conversion, and\n'
        "  deletion from the DBI3 instrument.\n"
        '* The "kml" menu allows conversion of logs previously downloaded from the DBI3\n'
        "  (the DBI3 does not need to be connected).  KML also allows edits to be set\n"
        "  for each individual log to trim excess records from the start or end, correct\n"
        "  altimeter offset, select Google Earth altitude mode and extend_to_ground settings.\n"
    )

    def preloop(self):
        self.do_doc("")
        self.do_version("")
        self.do_help("")

    def do_help(self, *args):
        """List available commands with "help" or detailed help with "help cmd"."""
        cmd.Cmd.do_help(self, *args)
        print("CURRENT LIST FILTER: [{}]".format(filter_text()))

    def do_doc(self, line):
        """Display basic application documentation."""
        print(self.my_header)

    def do_version(self, line):
        """Display the DBI3cli software version string"""
        print("DBI3cli version ({})\n".format(__version__))

    def do_config(self, line):
        """Set port, log path, kml path"""
        app_config.edit_config()

    def do_filter(self, line):
        """Filter DBI3 logs in the list - all|new|old|valid|invalid|DD[,...}  where DD=age_limit in days"""
        if line == "":
            print(
                "new_logs:{}  age_limit:{} Days  valid_only:{}".format(
                    app_config.CLI_new_logs, app_config.age_limit, app_config.CLI_skip_invalid
                )
            )
            return
        for ln in line.split(","):
            ln.strip()
            if ln == "all" or ln == "none":
                app_config.CLI_new_logs = False
                app_config.CLI_age_limit = None
                app_config.CLI_skip_invalid = False
            elif ln == "new":
                app_config.CLI_new_logs = True
                app_config.CLI_age_limit = None
            elif ln == "old":
                app_config.CLI_new_logs = False
            elif ln == "valid":
                app_config.CLI_skip_invalid = True
            elif ln == "invalid":
                app_config.CLI_skip_invalid = False
            else:
                # Try to parse an age limit string
                try:
                    age = int(ln)
                    if age <= 0:
                        app_config.age_limit = None
                        app_config.CLI_age_limit = None
                    else:
                        app_config.age_limit = age
                        app_config.CLI_age_limit = datetime.now(utc) - timedelta(days=age)
                except ValueError as e:
                    print("ERROR: unknown filter time {} : {}".format(ln, e))
                    continue
        print("CURRENT LIST FILTER: [{}]".format(filter_text()))

    def help_filter(self):
        print("Filter out the display of logs in the Logs and KML lists.")
        print("")
        print(" filter options - all|new|old|valid|invalid|#[,...}  where #=age_limit in days.")
        print("   none - turn off all filters, display all logs.")
        print("   new - only display logs newer than the currently latest log/KML file.")
        print("   old - reverses the new filter.")
        print("   valid - does not display logs that are invalid (have no GPS data).")
        print("   invalid - reverses the valid filter.")
        print("   # - does not display logs older than # days, zero clears this limit.")
        print("")
        print("Filter reduces the number of logs presented in the lists to a managable number")
        print("but can be opened up to display everything during log cleanup.")

    def do_logs(self, line):
        """Read log directory from DBI3. Select logs for download/delete."""
        try:
            Dbi3LogListCommands().cmdloop()
        except IOError as e:
            print("Can not access DBI3: {}".format(e))
            if e.errno == errno.EACCES:
                print(
                    "   On Linux you may need to add the user to the dialout group--\n"
                    "   'sudo addgroup $USER dialout'"
                )
        return Cmd_exit  # Global flag to indicate exit from nested Cmd

    def do_kml(self, line):
        """Select and convert logs to KML.
        Logs are kept in an SN specific subdirectory. If only 1 SN exists we
        automatically select it, else prompt for a specific SN to process.
        """
        global CLI_sn_list
        CLI_sn_list = []
        # Build a list of available SN subdirectories
        for sd in sorted(glob.glob(os.path.join(app_config.log_path, "SN*"))):
            if os.path.isdir(sd):
                CLI_sn_list.append(os.path.basename(sd))
        if len(CLI_sn_list) == 1:
            # only one SN recorded, skip directly to KML
            process_sn = CLI_sn_list[0]
        elif len(CLI_sn_list) == 0:
            print("There are currenly no LOGS available for KML conversion.")
            return
        else:
            print("AVAILABLE DBI3 LOG SNs:")
            for i, dbi_sn in enumerate(CLI_sn_list, 1):
                print("{}  {}".format(i, dbi_sn))
            new_val = input("Select line number of the SerialNumber to process: ").lower()
            try:
                j = int(new_val)
                if j < 1 or j > len(CLI_sn_list):
                    print("Line index [{}] is out of range".format(j))
                    return
                process_sn = CLI_sn_list[j - 1]
            except Exception as e:
                print("Can not select line [{}]: {}\n".format(new_val, e))
                return
        Dbi3KmlConversionCommands(process_sn).cmdloop()
        return Cmd_exit  # Global to indicate exit from nested Cmd

    def do_export(self, line):
        """Log or show the DBI3 instrument configuration settings

        Firmware upgrades of the DBI3 seem to reset the configuration data
        so it is a good idea to take a snapshot before upgrade.

        Default is to write to a DBI3 .cfg file in log_path but
        "export show" will write to the terminal.  The .cfg file name includes
        the DBI3 SN and timestamp when taken.

        See the DBI3 Instrument User Manual for setting definitions.
        """
        args = line.split()
        down_load = None
        report = ""
        try:
            # Initialize the serial communications and read the config data
            down_load = DBI3LogDownload(app_config)
            report, cfg_dict = down_load.get_DBI3_config()
        except IOError as e:
            print("Can not access DBI3: {}".format(e))
            if e.errno == errno.EACCES:
                print(
                    "   On Linux you may need to add the user to the dialout group--\n"
                    "   'sudo addgroup $USER dialout'"
                )
            return False
        if "show" in args:
            # Display the config on the terminal
            for res in report:
                print(res)
        else:
            # open config report file and write the data.
            # Embed the SN and current UTC time in the filename.
            time_string = datetime.now(utc).strftime("%Y%m%d_%H%M")
            cfg_file = "DBI3_{}_{}.cfg".format(down_load.dbi3_sn, time_string)
            cfg_file_path = os.path.join(app_config.log_path, cfg_file)
            # Add a header line to the report
            report.insert(
                0,
                "DBI3 {} configuration data on {} UTC".format(
                    down_load.dbi3_sn, datetime.now(utc).strftime("%c")
                ),
            )
            with open(cfg_file_path, "w") as f:
                for res in report:
                    f.write(res + "\n")

            if "json" in args:
                cfg_file = "DBI3_{}_{}.json".format(down_load.dbi3_sn, time_string)
                cfg_file_path = os.path.join(app_config.log_path, cfg_file)
                with open(cfg_file_path, "w") as f:
                    json.dump(cfg_dict, f, indent=4)

    def do_EOF(self, line):
        """Exit"""
        return True

    def do_exit(self, line):
        """Exit the application"""
        return True


class Dbi3LogListCommands(cmd.Cmd):
    """DBI3 Log download Cmd menu"""

    prompt = "(DBI3:Logs) "

    def preloop(self):
        self.down_load = DBI3LogDownload(app_config)
        self.my_list = []  # this contains our selection flag and the Log list element
        self.do_refresh("")
        self.prompt = "(DBI3:Logs:" + self.down_load.dbi3_sn + ") "
        self.do_help("")

    def do_help(self, *args):
        """List available commands with "help" or detailed help with "help cmd"."""
        cmd.Cmd.do_help(self, *args)
        print("CURRENT LIST FILTER: [{}]".format(filter_text()))

    def do_refresh(self, line):
        """Re-read the DBI3 log list"""
        if not app_config.verbose:
            sp = Spinner()  # py threading - DBI3 i/o does not yield to spinner :-(
        self.my_list = []
        for le in self.down_load.get_DBI3_log_list():
            self.my_list.append([le.new_file, le])
        if not app_config.verbose:
            sp.stop()
        print("DBI3 Log list length {}".format(len(self.my_list)))

    def do_list(self, line):
        """Display the DBI3 logs available for download.
Selected logs are marked with "*" after the line number.
"list selected" limits list to only selected logs.
"""
        print("\nCURRENT LIST FILTER: [{}]".format(filter_text()))
        only_sel = line == "selected"
        for i, le in enumerate(self.my_list):
            if only_sel is False or le[0] is True:
                print(
                    "{:3d} {} {}{}  {} to {}  duration:{}".format(
                        i,
                        "*" if le[0] else " ",
                        le[1].log_name,
                        "(new)" if le[1].new_file else "     ",
                        le[1].start_dt.astimezone().strftime("%H:%M:%S"),
                        le[1].end_dt.astimezone().strftime("%H:%M:%S%z"),
                        le[1].end_dt - le[1].start_dt,
                    )
                )

    def do_select(self, line):
        """Select/deselect LOG list rows for KML conversion. [all, none, new, #, #-#, -#]"""
        process_select_range(line, self.my_list)

    def help_select(self):
        print("Select/deselect LOG list rows for DBI3 download, convert or delete.")
        print("")
        print("Usage: select all|none|new|[-]#|#-#[,#|#-#...]")
        print("  all - select all rows")
        print("  none - deselect all rows")
        print("  new - select only new rows, deselect all others")
        print("  #    - select a specific row")
        print("  #-#  - select a range of rows, inclusive")
        print("")
        print("  Multiple numbers,ranges can be specified, seperated by commas")
        print('  If you prefix all number,ranges with "-" it becomes a deselect')

    def do_download(self, line):
        """Download the selected logs."""
        for le in self.my_list:
            if le[0]:  # list row is marked as selected
                if not app_config.verbose:
                    sp = Spinner()
                res = self.down_load.get_DBI3_log(le[1].name_start)
                le[0] = False  # clear the select flag
                if not app_config.verbose:
                    sp.stop()
                get_log().info(res)

    def do_convert(self, line):
        """Download AND convert the selected logs."""
        for le in self.my_list:
            if le[0]:  # list row is marked as selected
                if not app_config.verbose:
                    sp = Spinner()
                res = self.down_load.get_DBI3_log(le[1].name_start)
                if not app_config.verbose:
                    sp.stop()
                get_log().info(res)
                p_path = os.path.join(app_config.log_path, self.down_load.dbi3_sn)
                kml_name = le[1].start_dt.strftime("%Y%m%d_%H%M_{}".format(self.down_load.dbi3_sn))
                if not app_config.verbose:
                    sp = Spinner()
                dbi3_obj = Dbi3LogConversion(os.path.join(p_path, le[1].log_name), app_config)
                rtn, rtn_str = dbi3_obj.kml_convert(os.path.join(app_config.kml_path, kml_name))
                if not app_config.verbose:
                    sp.stop()
                if rtn < 0:
                    get_log().info(
                        "Convert {} to {} FAILED: {}".format(le[1].log_name, kml_name, rtn_str)
                    )
                elif rtn > 0 and app_config.verbose:
                    get_log().info("Convert {} to KML : {}".format(le[1].log_name, rtn_str))
                    le[0] = False  # clear the select flag
                elif rtn == 0:
                    get_log().info("Convert {} to KML\n{}".format(le[1].log_name, rtn_str))
                    le[0] = False  # clear the select flag

    def do_delete(self, line):
        """Delete the selected log files on the DBI3"""
        deleted_log = False
        for le in self.my_list:
            if le[0]:  # list row is marked as selected
                new_val = input(
                    "This will delete {} {} from the DBI3.\nAre you sure you want to continue? ".format(
                        le[1].name_start, le[1].log_name
                    )
                )
                if new_val.startswith("y"):
                    self.down_load.delete_DBI3_log(le[1].name_start)
                    deleted_log = True
                    get_log().info(
                        "Deleted log {} {} from the DBI3".format(le[1].log_name, le[1].name_start)
                    )

        # Delete has invalidated the list, so refresh
        if deleted_log:
            print("Refresh the log list--")
            self.do_refresh("")

    def do_back(self, line):
        """Back to Main menu"""
        return True

    def do_EOF(self, line):
        """Exit program"""
        global Cmd_exit
        Cmd_exit = True  # Global to indicate exit from nested Cmd
        return True

    do_exit = do_EOF


class Dbi3KmlConversionCommands(cmd.Cmd):
    """DBI3 Log to KML conversion menu"""

    prompt = "(DBI3:KML) "

    def __init__(self, dbi_sn):
        cmd.Cmd.__init__(self)
        self.prompt = "(DBI3:KML:{}) ".format(dbi_sn)
        self.sn_log_path = os.path.join(app_config.log_path, dbi_sn)
        app_config.update_dbi3_sn(dbi_sn)
        self.conv_list = None
        self.my_list = []

    def preloop(self):
        print("Reading the list of KML files...")
        self.conv_list = Dbi3KmlList(app_config)
        self.do_refresh("")  # Use the refresh command handler to fill the list
        print("KML list length {}".format(len(self.my_list)))
        self.do_help("")

    def do_help(self, *args):
        """List available commands with "help" or detailed help with "help cmd"."""
        cmd.Cmd.do_help(self, *args)
        print("CURRENT LIST FILTER: [{}]".format(filter_text()))

    def do_refresh(self, line):
        """Re-read the local DBI3 logs available for KML conversion, reset selections"""
        if not app_config.verbose:
            sp = Spinner()
        self.conv_list.refresh_list()
        self.my_list = []
        for le in self.conv_list.conversion_list:
            dbi3_obj = Dbi3LogConversion(le.log_filename, app_config)
            log_stats = dbi3_obj.log_summary()
            if app_config.CLI_skip_invalid:
                if log_stats.status <= 0:
                    if app_config.verbose:
                        print("Log {} dropped from list for status {} <= 0".format(le.log_name, log_stats.status))
                    continue
            # create my_list from conversion_list.  automatically select "new_file" and add the
            # field for KML track statistics.
            self.my_list.append([le.new_file, le, log_stats])
        if not app_config.verbose:
            sp.stop()

    def do_list(self, line):
        """Display the DBI3 logs available for KML conversion.
Selected logs are marked with "*" after the line number.
"list selected" limits list to only the selected logs.
"list long" prints an additional line of info per log file.
"""
        # Create and display a filter status line based on the settings
        print("\nCURRENT LIST FILTER: [{}]".format(filter_text()))
        args = line.split()
        only_sel = "selected" in args
        long_list = "long" in args
        for i, le in enumerate(self.my_list):
            if only_sel and not le[0]:
                continue
            print(
                "{:3d} {} {}{}  edits:{}  rcrds:{:5d}  duration:{}".format(
                    i,
                    "*" if le[0] else " ",
                    le[1].log_name,
                    "(new)" if le[1].new_file else "     ",
                    "Y" if le[1].override else " ",
                    le[2].status,
                    le[2].gps_end - le[2].gps_start if le[2].status > 0 else "---",
                )
            )
            if long_list:
                print(
                    "       {} to {}".format(
                        le[2].gps_start.astimezone().strftime("%H:%M:%S"),
                        le[2].gps_end.astimezone().strftime("%H:%M:%S%z"),
                    )
                )
        # Reminder about the current list filter
        print("CURRENT LIST FILTER: [{}]\n".format(filter_text()))

    def do_select(self, line):
        """Select/deselect LOG list rows for KML conversion. [all, none, new, #, #-#, -#]"""
        process_select_range(line, self.my_list)

    def help_select(self):
        print("Select/deselect LOG list rows for KML conversion.")
        print("")
        print("Usage: select all|none|new|[-]#|[-]#-#,[...]")
        print("  all - select all rows")
        print("  none - deselect all rows")
        print("  new - select only new rows, deselect all others")
        print("  #    - select a specific row")
        print("  #-#  - select a range of rows, inclusive")
        print("")
        print("  Multiple selections can be specified, seperated by commas")
        print('  If you prefix a number,ranges with "-" it becomes a deselect')

    def do_edit(self, line):
        """Override KML conversion for a specific log.  Requires a line number from the list for the specific log."""
        try:
            idx = int(line)
            le = self.my_list[idx]
        except ValueError:
            print("Requires a line number to edit from the current list output")
            return
        except Exception as e:
            print("Unable to edit {}: {}".format(line, e))
            return

        print("\nConversion options for: {}".format(le[1].log_name))
        app_config.edit_conversion_config(le[1].meta_name)
        self.do_refresh("")  # heavy hammer! Assume edit affected the list and refresh

    def do_convert(self, line):
        """Convert the currently selected DBI3 logs to KML"""
        # le array, [0]=select bool, [1]=ConversionList namedtuple
        for le in self.my_list:
            if le[0]:
                if not app_config.verbose:
                    sp = Spinner()
                dbi3_obj = Dbi3LogConversion(le[1].log_filename, app_config)
                rtn, rtn_str = dbi3_obj.kml_convert(le[1].kml_filename)
                if not app_config.verbose:
                    sp.stop()
                if rtn < 0:
                    get_log().info(
                        "Convert {} to KML {} FAILED: {}".format(
                            le[1].log_name, le[1].kml_name, rtn_str
                        )
                    )
                elif rtn > 0 and app_config.verbose:
                    get_log().info("Convert {} to KML: {}".format(le[1].log_name, rtn_str))
                    le[0] = False  # clear the select flag
                elif rtn == 0:
                    get_log().info("Convert {} to KML\n{}".format(le[1].log_name, rtn_str))
                    le[0] = False  # clear the select flag

                # TODO - this is a temporary hack for development
                #        csv enabled by command line flag
                if do_csv:
                    csv_filename = os.path.join(
                        os.path.expanduser("~"), "Documents", le[1].kml_name + ".csv"
                    )
                    rtn, rtn_str = dbi3_obj.csv_convert(csv_filename)
                    if rtn < 0:
                        get_log().info(
                            "Convert {} to CSV {} FAILED: {}".format(
                                le[1].log_name, csv_filename, rtn_str
                            )
                        )
                    elif rtn > 0 and app_config.verbose:
                        get_log().info("Convert {} to CSV: {}".format(le[1].log_name, rtn_str))
                    elif rtn == 0:
                        get_log().info("Convert {} to CSV\n{}".format(le[1].log_name, rtn_str))

    def do_back(self, line):
        """Back to Main menu"""
        return True

    def do_EOF(self, line):
        """Exit program"""
        global Cmd_exit
        Cmd_exit = True  # Global to indicated exit from nested Cmd
        return True

    do_exit = do_EOF


def process_select_range(line, my_list):
    """Given selection string, process the list to update the select flag

    my_list is a list of lists.  It contains the T/F select flag and the dictionary of the actual data
    row.  One of the row elements must be named "new_file" to be used for "new" selection.

    The selection string can be one or more comma separated specifiers:
      all
      none
      N
      -N
      N-N
      -N-N

    :param str line: String containing one or more comma separated selection specs
    :param list my_list: list of rows, each row is a list of two elements, select=T/F and dictionary
    :result: my_list select field is altered as specified
    """
    ln = line.lower()
    for line in ln.split(","):
        line = line.strip()
        if line == "":
            continue
        sel = None
        sel_new = False
        if "all" in line:
            sel = True
        elif "none" in line:
            sel = False
        elif "new" in line:
            sel_new = True
        if sel is not None or sel_new:
            for le in my_list:
                if not sel_new:
                    le[0] = sel
                else:
                    le[0] = le[1].new_file
            continue  # Done with this select specifier

        # not a full sweep so check for specific numbers
        # Leading '-' indicates this is a deselect
        # TODO collect all indicies before changing anything
        if line[0] == "-":
            sel_spec = line[1:]
            sel = False
        else:
            sel_spec = line
            sel = True
        # now process for N or N-N
        rng_spec = sel_spec.split("-")
        if rng_spec[0] == "":
            print("ERROR: invalid select specifier {}".format(sel_spec))
        try:
            beg_idx = int(rng_spec[0])
        except ValueError:
            print("ERROR: invalid select specifier {}".format(line))
            return
        if len(rng_spec) == 1:
            end_idx = beg_idx + 1
        else:
            try:
                end_idx = int(rng_spec[1]) + 1
            except ValueError:
                print("ERROR: invalid select specifier {}".format(line))
                return
        if beg_idx < 0 or beg_idx >= len(my_list) or end_idx <= beg_idx or end_idx > len(my_list):
            print("ERROR: valid select index range is 0 through {}".format(len(my_list) - 1))
            return
        for i in range(beg_idx, end_idx):
            my_list[i][0] = sel


def __verify_log_path(a_path):
    """Verify a directory path exists or attempt to create the leaf"""
    try:
        os.mkdir(a_path)
    except OSError:
        if not os.path.isdir(a_path):
            return False
    return True


def _verify_paths():
    """Verify the log and kml paths exist or exit the application"""
    if not os.path.isdir(app_config.log_path):
        print("Log file path {} does not exist.".format(app_config.log_path))
        exit()
    if not os.path.isdir(app_config.kml_path):
        print("KML file path {} does not exist.".format(app_config.kml_path))
        exit()


def main():
    """Main to drive the command line parsing and dispatch.

    Default values are defined/altered in the following hierarchy:
    1. hardwired in the code
    2. override by .DBI3config
    3. override by command line
    """
    global app_config

    ap_description = """
Download and/or convert DBI3 log file(s) to KML format.  The
application defaults to interactive mode to select and convert specific logs.
  --sync is automatic mode to download
new logs (newer than any existing log) and automatically converting to KML.  The
log_path and kml_path default to ~/Documents/DBI3logs and ~/Documents/DBI3logs/kml.
To override the default, the initial DBI3cli execution must be without --sync and
edit config.
"""
    ap_epilog = """
The LOG output is directed to a log_path subdirectory "SNxxxxx/" for the DBI3 serial number.  The name
format is "YYYY_MM_DD_hh_mm_ss.log".  KML output to the kml_path has a filename format of
"YYYYMMDD_hhmm_SNxxxxx.kml".
"""

    # TODO Overwrite a debug log to catch operations and errors of a run.

    parser = argparse.ArgumentParser(description=ap_description, epilog=ap_epilog)
    parser.add_argument(
        "--sync",
        action="store_true",
        default=False,
        help="start non-interactive automatic download and conversion",
    )
    parser.add_argument(
        "--file",
        action="store",
        dest="file",
        default=None,
        help="Single file conversion, this is the path to a single DBI3 log file "
        + "that will be converted to a single KML file in the same directory.",
    )
    parser.add_argument(
        "--fields",
        action="store",
        default=DBI_DEFAULT_LOG_FIELDS,
        type=lambda s: s.split(","),
        help="Which DBI3 data fields should be included in the KML output, default={}, "
        + "choices={}, ALL turns on all fields".format(
            ",".join(DBI_DEFAULT_LOG_FIELDS), ",".join(DBI_ALL_LOG_FIELDS)
        ),
    )
    parser.add_argument(
        "--altitudemode",
        action="store",
        default=None,
        choices=["absolute", "clampToGround", "relativeToGround"],
        help="Google Earth display mode for track altitude, default=absolute",
    )
    parser.add_argument(
        "--extend_to_ground",
        action="store_true",
        default=None,
        help="Google Earth setting to extend track displays with verticle lines to the "
        + "ground. default=True",
    )
    parser.add_argument(
        "--useMetric",
        action="store_true",
        default=None,
        help="For additional profile graph data fields use meters per second for rate of climb, "
        + "kilometers per hour for speed, "
        + "Celsius for temperature, and meters for altitude.  "
        + "default=FPM, MPH, Fahrenheit, feet.  NOTE: Google Earth config controls "
        + "the map display units for Track Elevation and Speed.",
    )
    parser.add_argument(
        "--offset",
        action="store",
        dest="altitude_offset",
        type=float,
        default=0.0,
        help="USED WITH --file ARGUMENT ONLY: correction offset to apply to the pressure "
        + "altitude, default=0.0",
    )
    # TODO do we want command line override?
    # parser.add_argument('--log_path', action='store', dest='log_path', default=None,
    #                     help='destination path for the output log files.')
    # parser.add_argument('--kml_path', action='store', dest='kml_path', default=None,
    #                     help='destination path for the output KML files.')
    parser.add_argument(
        "--age_limit",
        action="store",
        default=None,
        help="age limit in days for looking back at old logs and KML files. default=no limit",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=None,
        help="verbose debug output during processing",
    )
    parser.add_argument(
        "-V", "--version", action="version", version="%(prog)s (" + __version__ + ")"
    )
    parser.add_argument(
        "--csv",
        action="store_true",
        default=False,
        help="DEVELOPMENT: if true, when kml:convert is run it will also output a csv file to the "
        + "{HOME}/Documents directory",
    )
    args = parser.parse_args()

    # DEV temporary csv flag
    global do_csv
    do_csv = args.csv

    print("")  # put a blank line before application output

    # Read the optional config file and update specified settings
    # ==== Command line arguments override the config file without altering the config file
    app_config = Dbi3ConfigOptions(
        altitudemode=args.altitudemode,
        extend_to_ground=args.extend_to_ground,
        fields_choice=args.fields,
        kml_use_metric=args.useMetric,
        age_limit=None if args.age_limit is None else int(args.age_limit),
        verbose=args.verbose,
    )

    if app_config.age_limit is not None:  # If age_limit is set, create the datetime equivelent
        app_config.CLI_age_limit = datetime.now(utc) - timedelta(days=app_config.age_limit)
    else:
        app_config.CLI_age_limit = None
    app_config.CLI_new_logs = app_config.filter_new
    app_config.CLI_skip_invalid = app_config.filter_invalid
    if args.file is not None:
        # For manual file conversion, we don't need to initialize a DBI3 config file,
        # use any existing config file plus command line options.
        if args.file.startswith("~/"):
            # Handle HOME directory expansion
            args.file = os.path.join(os.path.expanduser("~"), args.file[2:])
        args.file = os.path.realpath(args.file)  # clean up the path
        kml_file = os.path.splitext(args.file)[0] + "_DBI3"
        if not app_config.verbose:
            sp = Spinner()
        dbi3_obj = Dbi3LogConversion(args.file, app_config, altitude_offset=args.altitude_offset)
        rtn, rtn_str = dbi3_obj.kml_convert(kml_file)
        if not app_config.verbose:
            sp.stop()
        if rtn < 0:
            print("Convert {} to {} FAILED: {}".format(args.file, kml_file, rtn_str))
        elif rtn > 0 and app_config.verbose:
            print("Convert {} to KML: {}".format(args.file, rtn_str))
        elif rtn == 0:
            print("Convert {} to KML\n{}".format(args.file, rtn_str))

    elif args.sync:
        # Non-interactive sync with the DBI3
        if not os.path.isfile(DBI_CONF_FILE):
            # non-interactive sync without a DBI_CONF_FILE file, attempt auto configure
            if not app_config.non_interactive_auto_config():
                print("Auto config failed")
                sys.exit(-2)

        _verify_paths()
        init_logger(app_config=app_config)
        process_dbi()
    else:
        if not os.path.isfile(DBI_CONF_FILE):
            print("\n########## Initial Configuration ##########\n")
            print("The default location for DBI3 log files is:\n    {}".format(DEF_LOG_PATH))
            print("And the default for KML output files is:\n    {}".format(DEF_KML_PATH))
            new_val = input("Is this OK (y/n)? ").lower()
            if new_val.startswith("y"):
                app_config.non_interactive_auto_config()
            # Regardless of auto_config, drop into config edit.
            print("log_path {} kml_path {}".format(app_config.log_path, app_config.kml_path))
            app_config.edit_config()

        _verify_paths()
        init_logger(app_config=app_config)
        Dbi3InteractiveCommandLine().cmdloop()

    return 0
