from __future__ import print_function
import os

try:
    from __pyinstaller__ import __pyinstaller__
except ImportError:
    # no __pyinstaller__
    # we are running inside the repo, update __version__.py with the latest
    # commit information
    from setuptools_scm import get_version

    try:
        version = get_version()
    except UserWarning:
        raise Exception('GIT must be in the path for get_version() to work')

    with open(os.path.join('lib', '__version__.py'), 'w') as v_file:
        print('# development run generated version from git', file=v_file)
        print('__version__ = "{}"'.format(version), file=v_file)
