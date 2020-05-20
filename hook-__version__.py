"""pyinstaller hook file

The should update the __version__ file from git information
"""
from __future__ import print_function
from setuptools_scm import get_version

version = get_version()

with open('__version__.py', 'w') as v_file:
    print('# pyinstaller version from git', file=v_file)
    print('__version__ = "{}"'.format(version), file=v_file)