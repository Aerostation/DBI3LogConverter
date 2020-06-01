# DBI3LogConverter
DBI3 log handling has split into two applications.  The original **DBI3LogConverter** converts
a single log file into KML, but it has not been kept up to date and may not work (21Aug2018).
The newer application **DBI3cli** includes code to download files from the DBI3, convert those files to KML, and allow single file conversion like the original DBI3LogConverter.  UNICSV output support is currently disabled.

This application reads Digitool DBI3 log files and converts them to common formats such as KML.

Log files on the DBI3 must first be downloaded to the PC before conversion.

It is possible to create a metadata file for any LOG file that will contain overrides for the KML conversion.  Things like altitude offset (when the altimeter setting was wrong), trim_start/end_times when there are
excess records at the start/end of the LOG file that you wish to exclude from the KML output.  The metadata file is the same basename as the log file (no extension) preceeded by "." to make it a hidden file.
It will be used anytime the log is converted.

The default mode of operation is interactive menus.  There is also "--sync" which automatically
downloads new logs (newer that the newest currently on the PC) and automatically converts to
KML.  The "--file" option allows the conversion of a single log file in any directory into KML in the same
directory.

If the application has not be configured before the first interactive or --sync run, it will
default log_path to *~/Documents/DBI3logs*, kml_path to *~/Documents/DBI3logs/kml*, and comm
port to None.  Comm port=None causes the application to search the USB for the correct
VID/PID used by the DBI3 interface chip.

For the end user, this python script should be packaged into a self contained executable that requires no other installations on the users computer (currently limited to 64-bit Windows 10)

The application uses basename of the DBI3 log file with some "_" removed as the basename of the KML output file.  The SN of the DBI3 is added to the name to differentiate multiple DBI3 sources.

NOTE:  THE FOLLOWING IS NO LONGER CORRECT ---
From CMD terminal (Windows Key, type cmd, select "Command Prompt")
```command
C:\Users\{username}> cd Downloads
C:\Users\{username}\Downloads> DBI3LogConverter.exe -d . 2018_03_25_13_43_18.log
  or
C:\Users\{username}\Downloads> DBI3LogConverter.exe -d . 2018_03*.log
```
Assumes you saved the logs in your Documents directory and want to place the resulting KML in the same directory



Currently the DBI3cli app will output KML with additional data by default.  [DISABLED- UNICSV is optional with a command line option.]

There are still questions:
- If there are data dropouts, e.g. the top temp is not always available, what can we do in the KML output (select an identifiable default)
- Currently, missing GPS data records are simply dropped.  The MAP display will simply show a potential straight line to the next data point.
- Should some or all of the additional data fields be optional in the KML to reduce KML size?  YES, additional data fields are configurable.
- The application will currently overwrite any existing output KML of the same name.  What should it do?

ROADMAP -
- Add gui front end.
- Automate build version increment

####BUILD -

Pyinstaller is used to package DBI3cli into a single executable file for Windows 10 and Linux.
Pyinstaller must be installed before build can run.

The build process is now driven by build/build.sh for both Windows 10 and Linux.  It 
creates a clean copy of source file in build/app, updates the build version, and runs pyinstaller.

On windows this s done from a "GIT Bash" window (part of Git for Windows https://gitforwindows.org/) which is a Linux
 like format and has
git in the PATH for automatic versioning.

From top level of the repo:
```commandline
build/build.sh
```
The dist and work subdirectories used by pyinstaller are now created in the temporary
build/app subdirectory.

ORIGINAL PROCEDURE obsoleted by build.sh-

Pyinstaller has an import hook for \__version__.py that constructs the version string from git tag and commit information.  It uses setuptools_scm to do the formatting (usually referenced in setup.py)

BUILD - The Windows 10 conversion to EXE is currently done in a cmd window with
(pyinstaller hook for __version__ requires "git" be in the windows path now):
```command
set Path=%Path%;C:\Program Files\git\bin
cd C:\Users\thornton\Documents\git\DBI3LogConverter
C:\Python27\Scripts\pyinstaller --clean --workpath ..\build --distpath ..\dist DBI3cli --additional-hooks-dir=hooks
  or
C:\Python27\Scripts\pyinstaller --clean --workpath ..\build --distpath ..\dist --onefile --additional-hooks-dir=hooks --console DBI3cli
```

BUILD UBUNTU - on HOTAIR:
```bash
source ~/PyEnvs/DBI3dev/bin/activate
pyinstaller --clean --additional-hooks-dir=hooks DBI3cli
  or
pyinstaller --clean --distpath ./dist/onefile --onefile --additional-hooks-dir=hooks DBI3cli
```
