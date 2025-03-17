#!/usr/bin/env python3
"""End To End Tester DB Recorder main start
Title                   : end-to-end-tester
Author                  : Justas Balcas
Email                   : jbalcas (at) es.net
@Copyright              : Copyright (C) 2025 ESnet
Date                    : 2025/03/14
"""
import time
from EndToEndTester.utilities import getConfig, setSenseEnv, getLogger, getUTCnow
from EndToEndTester.dbrecorder import FileParser

if __name__ == '__main__':
    logger = getLogger(name='Tester', logFile='/var/log/EndToEndTester/DBRecorder.log')
    yamlconfig = getConfig()
    startimer = getUTCnow()
    nextRun = 0
    setSenseEnv(yamlconfig)
    runner = FileParser(yamlconfig)
    while True:
        if nextRun <= getUTCnow():
            logger.info("Timer passed. Running main")
            nextRun = getUTCnow() + 60
            runner.main()
        else:
            logger.info(f"Sleeping for {yamlconfig['sleepbetweenruns']} seconds. Timer not passed")
            logger.info(f"Next run: {nextRun}. Current time: {getUTCnow()}. Difference: {nextRun - getUTCnow()}")
            time.sleep(60)
