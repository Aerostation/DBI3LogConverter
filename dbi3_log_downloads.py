#!/usr/bin/python
# vim: set sw=4 st=4 ai expandtab:
"""
DBI3 log names appear to be timestamps that are RAD26 encoded using 7 uppercase A-Z characters.

DBI3 log list consists of 2 7-character strings representing the start and stop time.
The 7 character string are RAD26 encoded using 7 uppercase A-Z characters.
The resulting numbers are in DOS FAT timestamp encoded format.

2 Bytes - Date
Bits    Description
15-9    Year (0 = 1980, 119 = 2099 supported under DOS/Windows, theoretically up to 127 = 2107)
8-5     Month (1-12)
4-0     Day (1-31)

2 Bytes - Time (2 second resolution)
Bits    Description
15-11   Hours (0-23)
10-5    Minutes (0-59)
4-0     Seconds/2 (0-29)

The original DigiTool download application would create filename of the form YYYY_MM_DD_HH_MM_SS.log
I changed the suffix to "_DBI3.log" to flag the source of these log files.
"""
import os
import serial
from datetime import datetime, timedelta, tzinfo
import json
import collections

__version__ = '0.1.alpah1'

# Define a named tuple for DBI3 log entry rows
LogList = collections.namedtuple('LogList', 'name_start name_end start_dt end_dt log_name new_file meta_name override')


class DBI3LogDownload:
    """Class to access DBI3 via serial port.

    Known commands:
        fs stop - stop any current logging, return ok/nok\n\r
        md mach - unknown, return ok\n\r
        sn - return serial number string SN12345\n\r
        fs list - returns log list\n\r follow with fs stop or md mach to gen ok/nok to indicate end"""
    ORD_A = ord('A')

    DBI3_EOL = '\n\r'  # DBI3 uses backward EOL. std since the teletype has been \r\n (allowed
                       #  carriage to physically return during line-feed

    MD_MACH = 'md mach'
    FS_STOP = 'fs stop'
    # DBI3 response to simple commands is ok or nok, sometimes we need to know the specific
    # response, others we just need any valid response.
    RESP_OK = ['ok']
    RESP_NOK = ['nok']
    RESP_ANY = ['ok', 'nok']

    log_path = None
    com_port = None
    age_limit = None  # to reduce clutter, we can set an optional age limit, older DBI3 logs are ignored
    new_limit = None
    verbose = None
    debug = False
    serial_fd = None  # initialized to the serial file descriptor for the DBI3 serial comm port

    dbi3_sn = None  # will contain the DBI serial number when the port is opened.

    def __init__(self, log_path='/tmp/DBI3', com_port='/dev/ttyDBI3', verbose=False, age_limit=None, valid_only=False):
        if log_path is None or not os.path.isdir(log_path):
            raise IOError('Log file path {} does not exist.".format(log_path)')
        if com_port is None or not os.path.exists(com_port):
            raise IOError("Comm port {} does not exist.".format(com_port))
        self.log_path = log_path
        self.com_port = com_port
        self.verbose = verbose
        self.age_limit = age_limit
        self.valid_only = valid_only
        # The determine "new" logs we need to know the latest log in log_path
        dt = None
        for item in sorted(os.listdir(self.log_path), reverse=True):
            if not os.path.isfile(os.path.join(self.log_path, item)):
                continue
            try:
                dt = datetime.strptime(item, "%Y_%m_%d_%H_%M_%S_DBI3.log")
            except ValueError as e:
                if self.debug:
                    print('Parse error of {}:{}'.format(item, e.message))
            if dt is not None:
                self.new_limit = dt.replace(tzinfo=self.utc) + timedelta(seconds=1)  # make new_limit timezone aware
                break

    def __radix26_to_int(self, rad26):
        """ DBI3 log names are radix 26 encoded string.  Seven upper case characters
        where each character is a number from 0-26 and converts to a 32bit integer.

        :param str rad26: 7 character log name, Radix 26 encoded
        :return int: Translation of rad26 to integer
        """
        encoded_int = 0

        for i in list(rad26):
            encoded_int = encoded_int * 26
            encoded_int = encoded_int + (ord(i) - self.ORD_A)
        return encoded_int

    class UTC(tzinfo):
        """UTC tzinfo"""

        def utcoffset(self, dt):
            return timedelta(0)

        def tzname(self, dt):
            return "UTC"

        def dst(self, dt):
            return timedelta(0)

    utc = UTC()  # tzinfo for UTC

    def __fat_to_datetime(self, rad26):
        """
        Convert 7 character log name to datetime.

        The 7 character string is RAD26 encoded using 7 uppercase A-Z characters.
        The resulting numbers are in DOS FAT timestamp encoded format.

        2 Bytes - Date
        Bits    Description
        15-9    Year (0 = 1980, 119 = 2099 supported under DOS/Windows, theoretically up to 127 = 2107)
        8-5     Month (1-12)
        4-0     Day (1-31)

        2 Bytes - Time (2 second resolution)
        Bits    Description
        15-11   Hours (0-23)
        10-5    Minutes (0-59)
        4-0     Seconds/2 (0-29)

        :param str rad26: 7 character log name, Radix 26 encoded
        :return datetime: Translation of rad26
        """
        fat = self.__radix26_to_int(rad26)
        second = (fat & 0x1F) * 2
        fat >>= 5
        minute = fat & 0x3F
        fat >>= 6
        hour = fat & 0x1F
        fat >>= 5
        day = fat & 0x1F
        fat >>= 5
        month = fat & 0xF
        fat >>= 4
        year = (fat & 0x7F) + 1980
        return datetime(year, month, day, hour, minute, second, tzinfo=self.utc)

    def __initialize_dbi3_serial_port(self):
        """Initialize the comm port for DBI3 communications.

        Read any pending data from the DBI3.

        :return:
        :raise IOError: If the comm port does not exist.
        """
        if self.serial_fd is not None:
            return  # serial port is already initialized

        if not os.path.exists(self.com_port):
            raise IOError('initialize serial port {} does not exist'.format(self.com_port))

        self.serial_fd = serial.Serial(self.com_port, 115200, timeout=1)
        self.serial_fd.dtr = True
        self.serial_fd.rts = True

        # Ensure any pending data is flushed from the DBI3
        while True:
            rd_cnt = self.serial_fd.in_waiting + 1  # read for 1 extra char, timeout if it doesn't arive.
            res = self.serial_fd.read(rd_cnt)
            if len(res) < rd_cnt:
                # read was short, we must have timed out waiting, DBI3 finished any output
                break

    def __do_DBI3_cmd(self, cmd, allowed_resp):
        """
        Send a command to the DBI3, read and compare the response to the allowed list.

        :param str cmd: command string to send, does not include any trailing EOL
        :param list,str allowed_resp: allowed response strings
        :return str: The stripped response
        :raise IOerror:  If the response is not in the allowed list
        """
        if self.serial_fd is None:
            # The first command ensures the serial port has been initialized.
            self.__initialize_dbi3_serial_port()

        self.serial_fd.write(cmd + '\r')
        res = self.__readDbi3Line()
        # print 'fs stop result={}'.format(res)
        if res not in allowed_resp:
            raise IOError('cmd:{} expect:{} got:{}'.format(cmd, allowed_resp, res))
        return res

    def get_DBI3_log_list(self, new_logs_only=False):
        """Retrieve the sorted DBI3 log list.

        Log names consist of 2 strings containing the log start/end times in DOS FAT
        timestamp format, encoded in radix26.

        Per the original DigiTool log download, the output filenames are encoded as
        YYYY_MM_DD_hh_mm_ss_DBI3.log (I added the _DBI3 to differentiate .log files!)

        After retrieving the log list from the DBI3 we check our configured log_path
        for corresponding log files and automatically select (mark download=True) each
        new DBI3 log.  Also retrieve any conversion metadata file for each log.

        :return list,namedtuple LogList: - LogList elements
            each list element named tuple of name_start=radix26_start, name_end=radix26_end,
            start_dt=start_datetime, end_dt=end_datetime, log_name=constructed log file name,
            download=True/False, metadata=None or conversion metadata.
        """
        self.__do_DBI3_cmd(self.MD_MACH, self.RESP_OK)
        self.__do_DBI3_cmd(self.FS_STOP, self.RESP_ANY)

        self.serial_fd.write('sn\r')
        res = self.__readDbi3Line()
        if res == '':
            raise IOError('cmd sn: returned empty')
        self.dbi3_sn = res
        print 'DBI3 {}'.format(res)

        self.serial_fd.write('fs list\rmd mach\r')

        dt_limit = None
        if new_logs_only and self.new_limit is not None:
            dt_limit = self.new_limit
        elif self.age_limit is not None:
            dt_limit = self.age_limit
        log_list = []

        if self.verbose:
            print 'RDT dt_limit:{} valid_only:{}'.format(dt_limit, self.valid_only)
        for res in iter(self.__readDbi3Line, None):
            if self.verbose:
                print 'RDT logs {}'.format(res)
            if res == 'ok' or res == 'nok':
                # List ended, we got the ok/nok from the md mach command.
                break
            rs = res.split(' ')
            start_dt = self.__fat_to_datetime(rs[0])
            # To handle scaling of the list, at this level we can ignore logs that are older that age_limit
            if dt_limit is not None and start_dt < dt_limit:
                continue
            stop_dt = self.__fat_to_datetime(rs[1])

            if self.valid_only:
                if stop_dt - start_dt < timedelta(seconds=3):
                    if self.verbose:
                        print 'IGNORE LOG {} due to short duration'.format(rs[0])
                    continue

            log_basename = start_dt.strftime('%Y_%m_%d_%H_%M_%S_DBI3')
            log_name = log_basename + '.log'
            log_metaname = '.' + log_basename  # hidden filename for conversion metadata

            log_file = os.path.join(self.log_path, log_name)
            log_metafile = os.path.join(self.log_path, log_metaname)

            if not os.path.isfile(log_file):
                download = True
            else:
                download = False

            metadata = None
            if os.path.isfile(log_metafile):
                # meta file to override some conversion settings
                with open(log_metafile, 'r') as meta:
                    metadata = json.load(meta)

            log_list.append(LogList(rs[0], rs[1], start_dt, stop_dt, log_name, download, log_metaname, metadata))

        log_list.sort()
        print 'log_list length {}'.format(len(log_list))
        if self.verbose:
            for rs in log_list:
                log_file = os.path.join(self.log_path, rs[4])

                if os.path.isfile(log_file):
                    fileExists = True
                else:
                    fileExists = False
                print 'LOG-{} {}  duration {}  new_file:{} override:{}'.format('   ' if fileExists else 'new', rs[2],
                                                                               rs[3] - rs[2], rs.new_file, rs.override)

        return log_list

    def delete_DBI3_log(self, name):
        print 'Will delete {}'.format(name)
        self.__do_DBI3_cmd(self.MD_MACH, self.RESP_OK)
        self.__do_DBI3_cmd(self.FS_STOP, self.RESP_ANY)

        self.serial_fd.write('fs del {}\r'.format(name))
        oldTimeout = self.serial_fd.timeout
        # DELETE appears to have no response, so a "md mach" is queued to produce an OK/NOK
        self.serial_fd.timeout = 20
        res = self.__do_DBI3_cmd(self.MD_MACH, self.RESP_OK)
        self.serial_fd.timeout = oldTimeout
        print 'fs delete ({}) result={}'.format(len(res), res)
        return True

    def __readDbi3Line(self):
        """Read serial port until eol string or timeout.

        Strip leading/trailing whitespace from the line.

        :return:
            None - if timeout waiting for EOL sequence
            str - stripped line from DBI3
        """
        output = ''
        len_eol = len(self.DBI3_EOL)
        while True:
            ch = self.serial_fd.read(1).decode('ascii')
            if len(ch) == 0:
                if len(output) != 0:
                    print "readDbi3Line timeout with-\n[{}]".format(output)
                return None  # timeout looking for eol
            output += ch
            if output[-len_eol:] == self.DBI3_EOL:
                break
        return output[0:-len_eol].strip()  # trim eol and white space off the return

    def get_DBI3_log(self, name):
        """Down load the specified log from the DBI3 serial connection.

        Read and write the log one line at a time to avoid massive buffers
        from a very long duration log.

        :param str name: rad26 name of the DBI3 log to download
        :return:
        """
        self.__do_DBI3_cmd(self.MD_MACH, self.RESP_OK)
        self.__do_DBI3_cmd(self.FS_STOP, self.RESP_ANY)

        start_dt = self.__fat_to_datetime(name)
        log_name = start_dt.strftime('%Y_%m_%d_%H_%M_%S_DBI3.log')
        log_file = os.path.join(self.log_path, log_name)

        self.serial_fd.write('fs read {}\r'.format(name))

        line_count = 0
        # Don't open the log until we have at least one line
        res = self.__readDbi3Line()
        if res is None or res == '':
            print 'LOG-{} zero length'.format(name)
            return

        with open(log_file, 'w') as log_out:
            while res:
                line_count += 1
                log_out.write(res + '\n')
                res = self.__readDbi3Line()
        print 'LOG download-{} {} ({})'.format(name, log_name, line_count)

    def download_selected_logs(self, log_list):
        """Access DBI3 via the serial port and download new log files.

        Download the current log list and compare against the destination log directory.
        Download logs that don't already exist.

            :param list,LogList log_list: list of logs on the DBI3
            :return int:
                0 - Success
                1 - no comm port available, skip the download
                -1 - error
       """

        # Download all logs that we don't already have
        for rs in log_list:
            if rs.new_file:
                self.get_DBI3_log(rs.name_start)

        # Clear any ongoing operations before we close the serial port
        self.__do_DBI3_cmd(self.FS_STOP, self.RESP_ANY)
        self.__do_DBI3_cmd(self.MD_MACH, self.RESP_OK)

        return 0
