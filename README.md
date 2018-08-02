# DBI3LogConverter
This application reads Digitool DBI3 log files and converts them to common formats such as KML and GPX

Log files on the DBI3 must first be downloaded to the PC before conversion.

It is possible to create a meta file for any LOG file that will contain overrides for the KML conversion.  Things like altitude offset (when the altimeter setting was wrong), trim_start/end_times when there are
excess records at the start/end of the LOG file that you wish to exclude from the KML.  The meta data file is the same basename as the log file (no extension) preceeded by "." to make it a hidden file.
It will be used anytime the log is converted.

Once the log destinations and comm port are properly configured, it is possible to run
the command with "--sync" which starts the non-interactive mode to download all new files
and automatically convert them.

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



Currently the app will output KML with additional data by default.  UNICSV is optional with a command line option.

There are still questions:
- If there are data dropouts, e.g. the top temp is not always available, what can we do in the KML output
- Currently, missing GPS data records are simply dropped.  The MAP display will simply show a potential straight line to the next data point.
- Should some or all of the additional data fields be optional in the KML to reduce KML size?
- The application will currently overwrite any existing output KML of the same name.  What should it do?
