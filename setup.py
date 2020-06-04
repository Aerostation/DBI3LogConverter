# vim: set shiftwidth=4 softtabstop=4 autoindent expandtab:
###########################################################################
# Copyright (C) Aerostation/Ronald Thornton 2018-2020
# All rights reserved.
###########################################################################
"""
cant run 'python setup.py sdist' from PyCharm terminal window because the Popen path
doesn't include git.
"""
from setuptools import setup, find_packages

setup(
    name="dbi3_access",
    # metadata to display on PyPI
    author="Ronald Thornton - Aerostation",
    author_email="thornton@aerostation.org",
    description='Download flight logs from DigiTool DBI3 and convert to KML',
    url="https://www.aerostation.org/",  # project home page, if any

    packages=find_packages(),
    include_package_data=True,
    use_scm_version=True,
    setup_requires=['setuptools_scm'],
    entry_points={
        'console_scripts': ['DBI3cli=dbi3_access.dbi3_main:main'],
    },

    # Project uses reStructuredText, so ensure that the docutils get
    # installed or upgraded on the target machine
    install_requires=["pyserial>=3.4", "setuptools-scm>=3.1.0", "simplekml>=1.3.0",],

    package_data={
        # If any package contains *.txt or *.rst files, include them:
        "": ["*.md", "*.odt"],
    },

    keywords=['aerostation', 'DigiTool', 'DBI3', 'hot air balloon', 'balloon', 'kml']
)