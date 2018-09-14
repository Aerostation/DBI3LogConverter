# DBI3LogConverter
DBI3 log handling has split into two applications.  The original DBI3LogConverter converts
a single log file into KML, but it has not been kept up to date and may not work (21Aug2018).
The newer application DBI3cli includes code to download files from the DBI3 as well as
convert those files to KML, and allows single file conversion like the original DBI3LogConverter.
  UNICSV support has currently been disabled.

This application reads Digitool DBI3 log files and converts them to common formats such as KML.

Log files on the DBI3 must first be downloaded to the PC before conversion.

It is possible to create a meta file for any LOG file that will contain overrides for the KML conversion.  Things like altitude offset (when the altimeter setting was wrong), trim_start/end_times when there are
excess records at the start/end of the LOG file that you wish to exclude from the KML.  The meta data file is the same basename as the log file (no extension) preceeded by "." to make it a hidden file.
It will be used anytime the log is converted.

The default mode of operation is interactive menus.  There is also "--sync" which automatically
downloads new logs (newer that the newest currently on the PC) and automatically converts to
KML.  The "--file" option allows the conversion of a single log file in any directory into KML in the same
directory.

If the application has not be configured before the first interactive or --sync run, it will
default log_path to ~/Documents/DBI3logs, kml_path to ~/Documents/DBI3logs/kml, and comm
port to None.  Comm port=None causes the application to search the USB for the correct
VID/PID used by the DBI3 interface chip.

For end user, this python script should be packaged into a self contained executable that requires no other installations on the users computer (currently limited to 64-bit Windows 10)

The application uses the base name of the DBI3 log file as the basename of the KML output file.

e.g:  THIS IS NO LONGER CORRECT---
From CMD terminal (Windows Key, type cmd, select "Command Prompt")
```
C:\Users\{username}> cd Downloads
C:\Users\{username}\Downloads> DBI3LogConverter.exe -d . 2018_03_25_13_43_18.log
  or
C:\Users\{username}\Downloads> DBI3LogConverter.exe -d . 2018_03*.log
```
Assumes you saved the logs in your Documents directory and want to place the resulting KML in the same directory



Currently the app will output KML with additional data by default.  UNICSV is optional with a command line option
 but currently disabled.

There are still questions:
- If there are data dropouts, e.g. the top temp is not always available, what can we do in the KML output
- Currently, missing GPS data records are simply dropped.  The MAP display will simply show a potential straight line to the next data point.
- Should some or all of the additional data fields be optional in the KML to reduce KML size?
- The application will currently overwrite any existing output KML of the same name.  What should it do?

ROADMAP -
- Add gui front end.
- Automate build version increment

BUILD - The Windows 10 conversion to EXE is currently done with:
 C:\Python27\Scripts\pyinstaller --workpath ..\build --distpath ..\dist DBI3cli