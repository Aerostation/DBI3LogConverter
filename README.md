# DBI3cli - DBI3 track log handler
This application reads Digitool DBI3 log files and converts them to common formats such as KML.

The original **DBI3LogConverter** application that converted
a single DBI3 log file into KML has been replaced (21Aug2018).
The newer application **DBI3cli** includes code to download and/or delete
log files from the
DBI3, convert those files to KML, and still allow single file conversion like the original
DBI3LogConverter.  CSV output support is a work in progress.

LOG files on the DBI3 must first be downloaded to the PC before conversion.  The LOG files
are never altered by this
application but simply used as the source for conversion to KML or other formats.

It is possible to create an optional metadata file for any LOG file that will contain
overrides for the KML conversion.  Override elements like altitude offset (when the altimeter
setting was incorrect) and trim_start/trim_end times when there are
excess records at the start/end of the LOG file that you wish to exclude from the KML
output.  The metadata file is the same basename as the log file with no extension and
prefixed by "." to make it a hidden file.
It will be used anytime the log is converted.

The default mode of operation is interactive menus.  There is also the command line "--sync" option which automatically
downloads new logs (newer that the newest currently on the PC) and automatically converts them to
KML.  The "--file" option allows the conversion of a single log file in any directory into KML in the same
directory.

If the application has not be configured before the first interactive or
"--sync" execution, it will
default the _log_path_ to *~/Documents/DBI3logs*, _kml_path_ to *~/Documents/DBI3logs/kml*, and comm
port to None.  Comm port=None causes the application to search the USB for the correct
VID/PID used by the DBI3 interface chip.

**NOTE:**
On Linux, the user running DBI3cli must have permission to open the USB port.  
This is usually accomplished by adding the user to the "dialout" group which
has R/W access to the serial ports.

For the end user, this python script is packaged into a self contained executable that
requires no other installations on the users computer (currently supported for 64-bit Windows 10 and Linux)

The LOG filenames are based on the original DigiTool download tool and are in the format
**YYYY_MM_DD_HH_MM_SS.log**. LOG files are stored in a subdirectory of _log_path_ that is the
Serial Number of the
DBI3 that created the LOG to differentiate logs from different DBI3 instruments.  The
KML output is stored in the _kml_path_ with filenames are in format
YYYYMMDD_HHMM_SNxxxxxx.kml that embeds the DBI3 serial number in the filename.

The **DBI3cli** app outputs the KML with additional DBI3 log data by default (e.g. COG, Variometer, Top Temp, ...).

###### There are still questions:
- If there are data dropouts, e.g. the top temp is not always available, what can we do in
  the KML output (currently selects an identifiable default value)
- Currently, missing GPS data records are simply dropped.  The MAP display will simply show
  a potential straight line to the next data point.
- Should some or all of the additional data fields be optional in the KML to reduce KML
  size?  YES, additional data fields are configurable.
- The application will currently overwrite any existing output KML of the same name.  What should it do?

#### ROADMAP -
- Add gui front end.
- Automate build version increment - DONE

#### CODE STYLE -
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
I have started enforcing "The Black Code Style" by running the **black** application
(actually python module).  The only current override is to increase the maximum line length
from the **black** default of 88 to 99.

With python env set to DBI3dev, in the top repository directory:
```commandline
black --check .
black .
```
The --check will report on the files that WOULD be changed.

#### DEVELOPMENT ENV -
Python 2.7 support may have broken due to limited datetime/timezone support.

On Linux, using virtualenv/virtualenvwrapper makes it easier to keep a clean
development environment that doesn't shift with system updates.

Env DBI3dev can be created with python3 as the interpreter and just the packages
required can be pip installed.

For my latest VirtualBox VM of Ubuntu 20.04:
```commandline
sudo adduser thornton dialout  # for access to /dev/tty/USB?
sudo adduser thornton vboxsf   # for VirtualBox share mount

sudo apt install python3, python3-dev, python3-virtualenv, python3-virtualenvwrapper
sudo apt install binutils, meld, vim, gitk, python3-tk-dbg
ADD TO .bashrc:
# Python virtualenv setup
export WORKON_HOME=/$HOME/.virtualenvs
#export PROJECT_HOME=$HOME/Devel
source /usr/share/virtualenvwrapper/virtualenvwrapper.sh

source ~/.bashrc

mkvirtualenv --python /usr/bin/python3 DBI3dev

workon DBI3dev  # switch to the DBI python development env
pip install simplekml, serial, pyinstaller, setuptools_scm

```

#### BUILD via build.sh -

Pyinstaller is used to package DBI3cli into a single executable file for Windows 10 and Linux.
Pyinstaller must be installed before build can run.

The build process is now driven by build/build.sh for both Windows 10 and Linux.  It
creates a clean copy of source file in build/app, updates the build version, and runs pyinstaller.

Prior to a release build, the repository should be up-to-date and then
```commandline
git tag -l -n4
git tag -a -m "tag message" n.m
git push origin n.m
```
to create the next tag number in the series.  Tags do not get pushed with commits and require their own push.  'git tag -l' lists the current tags and messages.

On windows the build is done from a "GIT Bash" window (part of Git for Windows
https://gitforwindows.org/) which is a Linux
like format and has
git in the PATH for the automatic versioning.

From top level of the repo:
```commandline
build/build.sh
```
The dist and work subdirectories used by pyinstaller are now created in the temporary
build/app subdirectory of the top level DBI3LogConverter/.

#### ORIGINAL PROCEDURE obsoleted by build.sh-

Pyinstaller has an import hook for \__version__.py that constructs the version string from git tag and commit information.  It uses setuptools_scm to do the formatting (usually referenced in setup.py)

BUILD - The Windows 10 conversion to EXE is currently done in a cmd window with
(pyinstaller hook for auto build __version__ requires "git" be in the windows path now):
```command
set Path=%Path%;C:\Program Files\git\bin
cd C:\Users\thornton\Documents\git\DBI3LogConverter
C:\Python27\Scripts\pyinstaller --clean --workpath ..\build --distpath ..\dist DBI3cli --additional-hooks-dir=hooks
  or
C:\Python27\Scripts\pyinstaller --clean --workpath ..\build --distpath ..\dist --onefile --additional-hooks-dir=hooks --console DBI3cli
```

#### BUILD UBUNTU - on HOTAIR:
```bash
source ~/PyEnvs/DBI3dev/bin/activate
pyinstaller --clean --additional-hooks-dir=hooks DBI3cli
  or
pyinstaller --clean --distpath ./dist/onefile --onefile --additional-hooks-dir=hooks DBI3cli
```
