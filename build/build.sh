#!/bin/bash

# Getting automatic version strings working correctly with both frozen (via pyinstaller) code and development builds
# has been difficult.  The build script drives pyinstaller using a clean temp directory for the applicaiont file and
# writes the frozen __version__ file with a __pyinstaller__ flag file so the application doesn't try to runtime
# update the version via git.

# This build.sh should be in the repo/build directory
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

if [[ $OS = 'Windows_NT' ]]
then
    PYTHON_CMD='/c/Python27/python'
    PYINSTALLER_CMD='/c/Python27/Scripts/pyinstaller'
else
    PYTHON_CMD='python'
    PYINSTALLER_CMD='pyinstaller'
fi

# Change to the build dir so relative paths will work.
cd $DIR
# Remove any existing temporary application tree and ensure we have the top level dir
rm -rf ./app
mkdir ./app

# Now copy application files to the clean app sub-directory for pyinstaller to work on
cp ../DBI3cli app/
(cd ..; find . -name '*.py' -not -path './build/*' | xargs cp -p --parent -t build/app)

# Write the pyinstaller __version__ file to the app tree
( cd ..;  # must run in the repo to execute get_version
$PYTHON_CMD - <<PyScript
from __future__ import print_function
import os
from setuptools_scm import get_version
from datetime import datetime

try:
    version = get_version()
    py_time = datetime.utcnow().isoformat('T')
except UserWarning:
    print('GIT must be in the path for get_version() to work')

with open(os.path.join('build', 'app', 'lib', '__version__.py'), 'w') as v_file:
    print('# dev run generated version from git', file=v_file)
    print('__version__ = "{}"'.format(version), file=v_file)
with open(os.path.join('build', 'app', '__pyinstaller__.py'), 'w') as v_file:
    print('__pyinstaller__ = "{}"'.format(py_time), file=v_file)
print('__version__ = {}  __pyinstaller__ = {}'.format(version, py_time))
PyScript
)

# Now execute the appropriate pyinstaller command line for the current OS
(
    cd $DIR/app
    if [[ $OS = 'Windows_NT' ]]
    then
        $PYINSTALLER_CMD --clean --workpath ./work --distpath ./dist --onefile --console DBI3cli

    else
        $PYINSTALLER_CMD --clean --workpath ./work --distpath ./dist --onefile DBI3cli
    fi
)
