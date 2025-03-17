#!/usr/bin/env python3
"""Automatic testing of SENSE Endpoints.
Title                   : end-to-end-tester
Author                  : Justas Balcas
Email                   : jbalcas (at) es.net
@Copyright              : Copyright (C) 2025 ESnet
Date                    : 2025/03/14
"""
# Some TODOs needed:
#    b) Validation is not always telling full truth - so we need to issue ping from SiteRM and wait for results;
#        and use those results for our reporting. If that fails - keep path created.
import os
import sys
import time
from EndToEndTester.utilities import getUTCnow, getConfig, getLogger
from EndToEndTester.tester import main

def createLockFile(lockfile):
    """Create a lock file to prevent multiple instances."""
    with open(lockfile, 'w', encoding="utf-8") as fd:
        fd.write(f"{str(os.getpid())} started at {getUTCnow()}")

def removeLockFile(lockfile):
    """Remove the lock file."""
    if os.path.exists(lockfile):
        os.remove(lockfile)

def isLocked(lockfile):
    """Check if the lock file exists."""
    return os.path.exists(lockfile)

def getLockContent(lockfile):
    """Get Lock file content"""
    if isLocked(lockfile):
        with open(lockfile, 'r', encoding="utf-8") as fd:
            return fd.read()
    return ""

if __name__ == '__main__':
    lockfilepath = "/tmp/endtester.lock"
    logger = getLogger(name='Tester', logFile='/var/log/EndToEndTester/Tester.log')
    yamlconfig = getConfig()
    startimer = getUTCnow()
    nextRun = 0

    if isLocked(lockfilepath):
        logger.error(f"Lock file {lockfilepath} exists. Exiting to prevent multiple instances.")
        logger.error(f"Locked file content: {getLockContent(lockfilepath)}")
        sys.exit(1)
    try:
        while True:
            if nextRun <= getUTCnow():
                logger.info("Timer passed. Running main")
                nextRun = getUTCnow() + yamlconfig['runInterval']
                main(yamlconfig, startimer, nextRun)
            else:
                logger.info(f"Sleeping for {yamlconfig['sleepbetweenruns']} seconds. Timer not passed")
                logger.info(f"Next run: {nextRun}. Current time: {getUTCnow()}. Difference: {nextRun - getUTCnow()}")
                time.sleep(yamlconfig['sleepbetweenruns'])
    except Exception as ex:
        logger.error(f'Got fatal exception: {ex}')
    finally:
        removeLockFile(lockfilepath)
