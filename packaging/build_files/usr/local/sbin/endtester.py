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
import time
from EndToEndTester.utilities import getUTCnow, getConfig, getLogger
from EndToEndTester.tester import main

if __name__ == '__main__':
    logger = getLogger(name='Tester', logFile='/var/log/EndToEndTester/Tester.log')
    yamlconfig = getConfig()
    startimer = getUTCnow()
    nextRun = 0
    while True:
        if nextRun <= getUTCnow():
            logger.info("Timer passed. Running main")
            nextRun = getUTCnow() + yamlconfig['runInterval']
            main(yamlconfig)
        else:
            logger.info(f"Sleeping for {yamlconfig['sleepbetweenruns']} seconds. Timer not passed")
            logger.info(f"Next run: {nextRun}. Current time: {getUTCnow()}. Difference: {nextRun - getUTCnow()}")
            time.sleep(yamlconfig['sleepbetweenruns'])
