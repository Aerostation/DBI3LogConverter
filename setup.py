# vim: set shiftwidth=4 softtabstop=4 autoindent expandtab:
###########################################################################
# Copyright (C) Aerostation/Ronald Thornton 2018-2020
# All rights reserved.
###########################################################################
"""
cant run 'python setup.py sdist' from PyCharm terminal window because the Popen path
doesn't include git.
"""
from setuptools import setup

setup(
    name="DBI3cli",
    # metadata to display on PyPI
    author="Ronald Thornton - Aerostation",
    author_email="thornton@aerostation.org",
    description='Download flight logs from DigiTool DBI3 and convert to KML',
    url="https://www.aerostation.org/",  # project home page, if any

    use_scm_version=True,
    setup_requires=['setuptools_scm'],
    entry_points={
        'console_scripts': ['DBI3cli=DBI3cli'],
    },

    # Project uses reStructuredText, so ensure that the docutils get
    # installed or upgraded on the target machine
    install_requires=["pyserial>=3.4", "setuptools-scm>=3.1.0", "simplekml==1.3.0",],

    package_data={
        # If any package contains *.txt or *.rst files, include them:
        "": ["*.md", "*.odt"],
    },

    keywords=['aerostation', 'DigiTool', 'DBI3', 'hot air balloon', 'balloon', 'kml']
)