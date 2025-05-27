#!/usr/bin/env python3
# pylint: disable=line-too-long
"""Automatic testing of SENSE Endpoints. (Utilities, like config loader)
Title                   : end-to-end-tester
Author                  : Justas Balcas
Email                   : jbalcas (at) es.net
@Copyright              : Copyright (C) 2025 ESnet
Date                    : 2025/03/14
"""
import os
import sys
import time
import json
import shutil
import logging
import logging.handlers
from datetime import datetime, timezone
import requests
from yaml import safe_load as yload
from yaml import safe_dump as ydump


def pauseTesting(fname):
    """Pause testing - in future action might come from SENSE-O"""
    if os.path.isfile(fname):
        return True
    return False


def getLogger(
    name="loggerName", logLevel=logging.DEBUG, logFile="/tmp/app.log", logtoStdout=False
):
    """
    Get or create a logger that works across processes by logging to a file.
    """
    logger = logging.getLogger(name)
    if not logger.hasHandlers():
        logger.setLevel(logLevel)
        # Create a file handler that supports multi-process logging
        handler = logging.handlers.RotatingFileHandler(
            logFile, maxBytes=10 * 1024 * 1024, backupCount=100
        )
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

        if logtoStdout:
            stdout_handler = logging.StreamHandler(sys.stdout)
            stdout_handler.setFormatter(formatter)
            logger.addHandler(stdout_handler)

        logger.propagate = (
            False  # Prevent duplicate logs from propagating to root logger
        )

    return logger


def moveFile(filePath, newDir):
    """Move a file to a new directory."""
    try:
        checkCreateDir(newDir)
        newFName = f"{getUTCnow()}-{os.path.basename(filePath)}"
        newFilePath = os.path.join(newDir, newFName)
        shutil.move(filePath, newFilePath)
        print(f"File moved to: {newFilePath}")
        return newFilePath
    except Exception as ex:
        print(f"Error moving file: {ex}")
    return None


def renameFile(filePath, newDir, newFName):
    """Rename a file and move it to a new directory."""
    try:
        checkCreateDir(newDir)
        newFilePath = os.path.join(newDir, newFName)
        shutil.move(filePath, newFilePath)
        print(f"File moved to: {newFilePath}")
        return newFilePath
    except Exception as ex:
        print(f"Error moving file: {ex}")
    return None


def checkCreateDir(workdir):
    """Check if directory exists, if not, create it"""
    if not os.path.exists(workdir):
        os.makedirs(workdir)


def timestampToDate(timestamp):
    """Convert a timestamp to a UTC date string in YYYY-MM-DD format."""
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")


def getUTCnow():
    """Get UTC Time."""
    return int(datetime.now(timezone.utc).timestamp())


def loadFileJson(filename):
    """Load File"""
    if not os.path.isfile(filename):
        print(f"Input {filename} is not a file. return empty dict")
        return {}
    with open(filename, "rb") as fd:
        try:
            return json.loads(fd.read())
        except json.JSONDecodeError as ex:
            print(f"Error in loading file: {ex}")
    return {}


def dumpFileJson(filename, data):
    """Dump File"""
    with open(filename, "wb") as fd:
        try:
            fd.write(json.dumps(data).encode("utf-8"))
        except json.JSONDecodeError as ex:
            print(f"Error in dumping file: {ex}")
    return {}


def loadJson(data):
    """Load JSON"""
    if not data:
        return {}
    if isinstance(data, (dict, list)):
        return data
    try:
        return json.loads(data)
    except json.JSONDecodeError as ex:
        print(f"Error in loading json dict: {ex}")
    return {}


def dumpJson(data):
    """Dump JSON"""
    try:
        return json.dumps(data)
    except json.JSONDecodeError as ex:
        print(f"Error in dumping json dict: {ex}")
    return {}


def dumpYaml(data):
    """Dump YAML"""
    try:
        return ydump(data, default_flow_style=False)
    except json.JSONDecodeError as ex:
        print(f"Error in dumping yaml dict: {ex}")
    return {}


def loadYaml(data):
    """Load YAML"""
    if isinstance(data, (dict, list)):
        return data
    try:
        return yload(data)
    except Exception as ex:
        print("Error in loading yaml dict: %s", ex)
        print("Data: %s", data)
        print("Data type: %s", type(data))
    return {}


def getConfig():
    """Get Config"""
    if not os.path.isfile("/etc/endtoend.yaml"):
        raise Exception("Config file /etc/endtoend.yaml does not exist.")
    with open("/etc/endtoend.yaml", "r", encoding="utf-8") as fd:
        return loadYaml(fd.read())


def setSenseEnv(config=None):
    """Set SENSE Environment point to configuration file"""
    if not config:
        config = getConfig()
    if "sense-auth" in config:
        os.environ["SENSE_AUTH_OVERRIDE"] = config["sense-auth"]
        return True
    return False


def fetchRemoteConfig(url, retries=3, sleep_time=30):
    """Fetch remote configuration."""
    errmsg = []
    for attempt in range(1, retries + 1):
        try:
            response = requests.get(url, timeout=60)
            if response.status_code == 200:
                return response.text
            msg = f"Attempt {attempt}: Failed with status code {response.status_code}"
            print(msg)
            errmsg.append(msg)
        except requests.RequestException as ex:
            msg = f"Attempt {attempt}: Exception occurred - {ex}"
            print(msg)
            errmsg.append(msg)
        msg = f"Retrying in {sleep_time} seconds..."
        print(msg)
        errmsg.append(msg)
        time.sleep(sleep_time)
    print("Failed to fetch the URL after multiple attempts.")
    if errmsg:
        raise Exception("\n".join(errmsg))
    return None


def refreshConfig(config):
    """Refresh config from remote location, if no remote - from local and return new config"""
    if config.get("configlocaction", None):
        config = loadYaml(fetchRemoteConfig(config["configlocation"]))
        return config
    return getConfig()
