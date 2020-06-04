# vim: set shiftwidth=4 softtabstop=4 autoincrement expandtab:
###########################################################################
# Copyright (C) Aerostation/Ronald Thornton 2020
# All rights reserved.
###########################################################################
import os
import sys
import logging
import logging.handlers

_logger = None
_MAX_AUDIT_SIZE = 1 * 1024 * 1024

def get_log():
    return _logger


def init_logger(name='DBI3cli', app_config=None):
    """Returns a logging object used to log and print to screen.

       Intended for INFO (audit) messages, ONLY INFO level will
       go to the log file.
    """
    global _logger
    if _logger is None:
        # compute path to the audit log file
        audit_file = os.path.join(app_config.log_path, 'audit_DBI3.log')
        try:
            audit_size = os.path.getsize(audit_file)
        except:
            audit_size = 0

        log = logging.getLogger(name)
        log.propagate = False  # don't bubble up to a higher logger
        log.setLevel(logging.DEBUG)

        auditlog = logging.handlers.RotatingFileHandler(audit_file, backupCount=10)
        auditlog.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
        auditlog.addFilter(info_filter())
        auditlog.setLevel(logging.INFO)
        log.addHandler(auditlog)
        # If the current file got to big, rotate before we write
        if audit_size >= _MAX_AUDIT_SIZE:
            auditlog.doRollover()

        log.info('DBI3cli starting')

        stdout = logging.StreamHandler(stream=sys.stdout)
        stdout.setFormatter(logging.Formatter('%(message)s'))
        stdout.setLevel(logging.DEBUG)
        log.addHandler(stdout)

        _logger = log
    return _logger


class info_filter():
    """Only allow INFO events thru this filter"""
    def filter(self, record):
        return record.levelno == logging.INFO