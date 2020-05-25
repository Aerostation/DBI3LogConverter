#!/usr/bin/python
# vim: set sw=4 st=4 ai expandtab:
"""
Classes to download and/or delete DBI3 log files on the DBI3

DBI3 log names are the encoded start and end times of the log.

DBI3 log list consists of 2 7-character strings representing the start and end time.
The 7 character strings are 32 bit integers, RAD26 encoded using uppercase A-Z characters.
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

The original DigiTool download application created filenames of the form YYYY_MM_DD_HH_MM_SS.log.
This format is retained, but the files are stored in a subdirectory of the form ./SN12345/ based on the
serial number of the DBI3 as read from the serial cli.  Firmware v1.2 log files contain a dummy SN
in the start line.

Some DBI3 serial cli commands don't produce an EOF indication (fs list, fs read).  Add an immediate 'md mach'
after the command and use the 'md mach' 'ok/nok' response as the command EOF.
"""
import os
import serial
from serial.tools.list_ports import comports
from datetime import datetime, timedelta
import json

try:
    from dbi3_common import LogList, utc
    from dbi3_config_options import Dbi3ConfigOptions
except ImportError:
    from .dbi3_common import LogList, utc
    from .dbi3_config_options import Dbi3ConfigOptions

__version__ = '0.1.alpah1'


class DBI3LogDownload:
    """Class to access DBI3 via serial port.

    From the base log_path, we store logs in a subdirectory named after the DBI3 serial number,
    for example "SN11005".

    Known commands:
        fs stop - stop any current logging, return ok/nok\n\r
        md mach - unknown, return ok\n\r
        sn - return serial number string SN12345\n\r
        fs list - returns log list\n\r follow with fs stop or md mach to gen ok/nok to indicate end"""

    DBI3_EOL = '\n\r'  # DBI3 uses backward EOL. std since the teletype has been \r\n (allowed
                       #  carriage to physically return during line-feed

    MD_MACH = 'md mach'
    FS_STOP = 'fs stop'
    # DBI3 response to simple commands is ok or nok, sometimes we need to know the specific
    # response, others we just need any valid response.
    RESP_OK = ['ok']
    RESP_NOK = ['nok']
    RESP_ANY = ['ok', 'nok']

    def __init__(self, app_config):
        """Initialize DBI3LogDownload and serial port.
        If called without a serial port parameter, attempt to find a USE serial port with the
        correct USB VID:PID that answers the 'sn' command.
        """
        self.app_config = app_config
        self.log_path = app_config.log_path
        self.com_port = app_config.com_port
        self.verbose = app_config.verbose
        self.age_limit = None
        self.debug = False
        self.serial_fd = None  # initialized to the serial file descriptor for the DBI3 serial comm port
        self.dbi3_sn = None  # will contain the DBI serial number when the port is opened/initialized.
        self.valid_only = app_config.CLI_skip_invalid

        self.readline_buf = bytearray()  # init buffer for our block mode readline
        if app_config.log_path is None or not os.path.isdir(app_config.log_path):
            raise IOError('Log file path {} does not exist.'.format(app_config.log_path))
        if self.com_port is None:
            # try to find the appropriate DBI3 comm port by USB VID:PID for FTDI FT230X
            for c_p in comports():
                if c_p.vid == 0x0403 and c_p.pid == 0x6015:
                    if self.com_port is not None:
                        raise IOError('Can not select a DBI3 comm port (duplicate USB VID:PID 0403:6015)')
                    else:
                        self.com_port = c_p.device
            if self.com_port is None:
                raise IOError('Can not find a DBI3 comm port (USB VID:PID 0403:6015)')
            print('DBI3 auto selected port {}'.format(self.com_port))
        elif not os.path.exists(self.com_port):
            raise IOError("Comm port {} does not exist.".format(self.com_port))
        self.__initialize_dbi3_serial_port()

    @staticmethod
    def __radix26_to_int(rad26):
        """ DBI3 log names are radix 26 encoded string.  Seven upper case characters
        where each character is a number from 0-26 and converts to a 32bit integer.

        :param str rad26: 7 character log name, Radix 26 encoded
        :return int: Translation of rad26 to integer
        """
        encoded_int = 0

        for i in list(rad26):
            encoded_int = encoded_int * 26
            encoded_int = encoded_int + (ord(i) - ord('A'))
        return encoded_int

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
        return datetime(year, month, day, hour, minute, second, tzinfo=utc)

    def __initialize_dbi3_serial_port(self):
        """Initialize the comm port for DBI3 communications.

        Read any pending data from the DBI3.

        Read the serial number from the DBI3 and set our global.

        Scan the SN subdirectory to determine the latest log file to determine "newer".

        :return:
        :raise IOError: If the comm port does not exist.
        :raise SerialException: on pyserial errors (derived from IOError)
        """
        if self.serial_fd is not None:
            return  # serial port is already initialized

        self.serial_fd = serial.Serial(self.com_port, 115200, timeout=2, rtscts=True)
        self.serial_fd.dtr = True

        # Ensure any pending data is flushed from the DBI3
        while True:
            rd_cnt = self.serial_fd.in_waiting + 1  # read for 1 extra char, timeout if it doesn't arive.
            res = self.serial_fd.read(rd_cnt)
            if len(res) < rd_cnt:
                # read was short, we must have timed out waiting, DBI3 finished any output
                break

        # ensure the DBI3 is in a good state
        self.__do_DBI3_cmd(self.MD_MACH, self.RESP_OK)
        self.__do_DBI3_cmd(self.FS_STOP, self.RESP_ANY)

        # Get the actual device serial number from the DBI3
        self.serial_fd.write(str.encode('sn\r'))
        res = self.__readDbi3Line()
        if res == '':
            raise IOError('cmd sn: returned empty')
        self.dbi3_sn = res

        # The determine "new" logs we need to know the latest log in log_path
        p_path = os.path.join(self.log_path, self.dbi3_sn)
        if os.path.isdir(p_path):
            dt = None
            for item in sorted(os.listdir(p_path), reverse=True):
                if not os.path.isfile(os.path.join(p_path, item)):
                    continue
                try:
                    dt = datetime.strptime(item, "%Y_%m_%d_%H_%M_%S.log")
                except ValueError as e:
                    if self.debug:
                        print('Parse error of {}:{}'.format(item, e.message))
                if dt is not None:
                    self.new_limit = dt.replace(tzinfo=utc) + timedelta(seconds=1)  # make new_limit timezone aware
                    if self.verbose:
                        print('DBI3 new file threshold: {}'.format(self.new_limit))
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

        self.serial_fd.write(str.encode(cmd + '\r'))
        res = self.__readDbi3Line()
        # print 'fs stop result={}'.format(res)
        if res not in allowed_resp:
            raise IOError('cmd:{} expect:{} got:{}'.format(cmd, allowed_resp, res))
        return res

    def get_DBI3_log_list(self, new_logs_only=None):
        """Retrieve the sorted DBI3 log list.

        Log names consist of 2 strings containing the log start/end times in DOS FAT
        timestamp format, encoded in radix26.

        Per the original DigiTool log download, the output filenames are encoded as
        YYYY_MM_DD_hh_mm_ss_DBI3.log (I added the _DBI3 to differentiate .log files!)

        After retrieving the log list from the DBI3 we check our configured log_path
        for corresponding log files and automatically select (mark download=True) each
        new DBI3 log.  Also retrieve any conversion metadata file for each log.

        :param bool new_logs_only:  overrides app_config filter setting for non-interactive sync
        :return list,namedtuple LogList: - LogList elements
            each list element named tuple of name_start=radix26_start, name_end=radix26_end,
            start_dt=start_datetime, end_dt=end_datetime, log_name=constructed log file name,
            download=True/False, metadata=None or conversion metadata.
        """
        if new_logs_only is None:  # optional param will override app_config
            new_logs_only = self.app_config.CLI_new_logs

        self.__do_DBI3_cmd(self.MD_MACH, self.RESP_OK)
        self.__do_DBI3_cmd(self.FS_STOP, self.RESP_ANY)

        self.serial_fd.write(str.encode('fs list\rmd mach\r'))

        p_path = os.path.join(self.log_path, self.dbi3_sn)

        dt_limit = None
        if new_logs_only and self.new_limit is not None:
            dt_limit = self.new_limit
        elif self.app_config.CLI_age_limit is not None:
            dt_limit = self.app_config.CLI_age_limit
        log_list = []

        if self.verbose:
            print('RDT dt_limit:{} valid_only:{}'.format(dt_limit, self.valid_only))
        for res in iter(self.__readDbi3Line, None):
            if self.verbose:
                print('RDT logs {}'.format(res))
            if res == 'ok' or res == 'nok':
                # List ended, we got the ok/nok from the md mach command.
                break
            rs = res.split(' ')
            start_dt = self.__fat_to_datetime(rs[0])
            # To handle scaling of the list, at this level we can ignore logs that are older that age_limit
            if dt_limit is not None and start_dt < dt_limit:
                continue
            stop_dt = self.__fat_to_datetime(rs[1])

            log_basename = start_dt.strftime('%Y_%m_%d_%H_%M_%S')
            log_name = log_basename + '.log'
            log_metaname = '.' + log_basename  # hidden filename for conversion metadata

            if self.valid_only:
                # Without download we can't determine if there are GPS records, we can only
                # base "valid" on a time delta.
                if stop_dt - start_dt < timedelta(seconds=3):
                    if self.verbose:
                        print('IGNORE LOG {} ({}) due to short duration'.format(rs[0], log_basename))
                    continue

            log_file = os.path.join(p_path, log_name)
            log_metafile = os.path.join(p_path, log_metaname)

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
        print('DBI3 Log list length {}'.format(len(log_list)))
        if self.verbose:
            for rs in log_list:
                print('LOG-{}  duration {}  new_file:{}  edits:{}'.format(rs[2], rs[3] - rs[2],
                                                                          rs.new_file, rs.override))

        return log_list

    def delete_DBI3_log(self, name):
        print('Will delete {}'.format(name))
        self.__do_DBI3_cmd(self.MD_MACH, self.RESP_OK)
        self.__do_DBI3_cmd(self.FS_STOP, self.RESP_ANY)

        self.serial_fd.write(str.encode('fs del {}\r'.format(name)))
        orig_timeout = self.serial_fd.timeout
        # DELETE appears to have no response, so a "md mach" is queued to produce an OK/NOK
        self.serial_fd.timeout = 20
        res = self.__do_DBI3_cmd(self.MD_MACH, self.RESP_OK)
        self.serial_fd.timeout = orig_timeout
        print('fs delete ({}) result={}'.format(len(res), res))
        return True

    def __readDbi3Line(self):
        """Read serial port until eol string or timeout.

        Strip leading/trailing whitespace from the line.

        :return:
            None - if timeout waiting for EOL sequence
            str - stripped line from DBI3
        """
        # Read serial port in blocks to optimize during LARGE log download.
        # Buffer any extra data until the next read line call.
        # Return line as a stripped string to ensure spaces and extra EOL characters
        # are removed (DBI3 EOL is \n\r which is reverse from TTY standard)

        # First thing, check if the buffer already has a complete line to return.
        i = self.readline_buf.find(b"\n")
        if i >= 0:
            # Return the line and remove it from the buffer
            r = self.readline_buf[:i]
            self.readline_buf = self.readline_buf[i + 1:]
            return r.decode('utf8').strip()
        while True:
            i = max(1, min(2048, self.serial_fd.in_waiting))
            data = self.serial_fd.read(i)
            if len(data) == 0:
                # zero data means this was a timeout and terminates read
                if len(self.readline_buf) != 0:
                    # This is probably an error!
                    print('RDT read timeout for EOL with data {}'.format(data))
                return ''
            i = data.find(b"\n")
            if i >= 0:
                # Found NL in read, prefix with any prior data, save remaining data
                r = self.readline_buf + data[:i]
                self.readline_buf[0:] = data[i + 1:]
                return r.decode('utf8').strip()
            else:
                # No NL yet, add to existing data and read again
                self.readline_buf.extend(data)
        # output = ''
        # len_eol = len(self.DBI3_EOL)
        # while True:
        #     ch = self.serial_fd.read(1).decode('ascii')
        #     if len(ch) == 0:
        #         if len(output) != 0:
        #             print "readDbi3Line timeout with-\n[{}]".format(output)
        #         return None  # timeout looking for eol
        #     output += ch
        #     if output[-len_eol:] == self.DBI3_EOL:
        #         break
        # return output[0:-len_eol].strip()  # trim eol and white space off the return

    def get_DBI3_log(self, name):
        """Down load the specified log from the DBI3 serial connection.

        Read and write the log one line at a time to avoid massive buffers
        from a very long duration log.

        :param str name: rad26 name of the DBI3 log to download
        :return:
        """
        self.__do_DBI3_cmd(self.MD_MACH, self.RESP_OK)
        self.__do_DBI3_cmd(self.FS_STOP, self.RESP_ANY)

        p_path = os.path.join(self.log_path, self.dbi3_sn)
        if not os.path.isdir(p_path):
            os.mkdir(p_path)
        start_dt = self.__fat_to_datetime(name)
        log_name = start_dt.strftime('%Y_%m_%d_%H_%M_%S.log')
        log_file = os.path.join(p_path, log_name)

        self.serial_fd.write(str.encode('fs read {}\rmd mach\r'.format(name)))

        line_count = 0
        beg_down = datetime.now()  # calculate elapsed time to read log
        # Don't open the log until we have at least one line
        res = self.__readDbi3Line()
        if res is None or res == '':
            print('LOG-{} zero length'.format(name))
            return

        with open(log_file, 'w') as log_out:
            while res:
                if res == 'ok' or res == 'nok':
                    # this is the 'md mach' response, the log is complete
                    break
                line_count += 1
                log_out.write(res + '\n')
                res = self.__readDbi3Line()
        print('LOG download-{} ({} records in {})'.format(log_name, line_count, datetime.now() - beg_down))

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

        return 0
