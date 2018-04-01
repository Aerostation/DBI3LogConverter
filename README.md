# DBI3LogConverter
This application reads Digitool DBI3 log files and converts them to common formats such as KML and GPX

For end user, this python script should be packaged into a self contained executable that requires no other installations on the users computer (currently limited to 64-bit Windows 10)

The application uses the base name of the DBI3 log file as the basename of the KML output file.

e.g:
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
