#!/bin/bash

# Getting automatic version strings working correctly with both frozen (via pyinstaller) code and development builds
# has been difficult.  The build script drives pyinstaller using a clean temp directory for the application files and
# writes the frozen __version__ file.

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

# Update the __version__ file to the latest git tag
( cd "$DIR/.." || return 1  # must run in the repo to execute get_version
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

with open(os.path.join('dbi3_access', 'lib', '__version__.py'), 'w') as v_file:
    print('# dev run generated version from git', file=v_file)
    print('__version__ = "{}"'.format(version), file=v_file)
print('__version__ = {} '.format(version))
PyScript
) || { echo "Create version file failed"; exit 1; }

# Change to the build dir so relative paths will work.
cd "$DIR" || exit
# Remove any existing temporary application tree and ensure we have the top level dir
rm -rf ./app
mkdir ./app

# Now copy application files to the clean app sub-directory for pyinstaller to work on
(
    cd "$DIR/.."
    cp DBI3cli build/app/
    find . -name '*.py' -not -path './build/*' -print0 | xargs -0 cp -p --parent -t build/app
) || { echo "Copy failed"; exit 1; }

# Now execute the appropriate pyinstaller command line for the current OS
echo "****Run pyinstaller"
(
    cd "$DIR/app"
    if [[ $OS = 'Windows_NT' ]]
    then
        $PYINSTALLER_CMD --clean --workpath ./work --distpath ./dist --onefile --console DBI3cli

    else
        $PYINSTALLER_CMD --clean --workpath ./work --distpath ./dist --onefile DBI3cli
    fi
) || echo "Pyinstaller failed"
# Now create a python application package
echo "****Run setuptools sdist"
(
    cd "$DIR/.."
    $PYTHON_CMD setup.py sdist
) || echo "setuptools sdist failed"
