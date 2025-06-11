#!/usr/bin/env python3
# pylint: disable=line-too-long
"""DB Backend for communication with database. Mainly we use mariadb
Title                   : end-to-end-tester
Author                  : Justas Balcas
Email                   : jbalcas (at) es.net
@Copyright              : Copyright (C) 2025 ESnet
Date                    : 2025/03/14
"""
import re
import os
from sense.client.workflow_combined_api import WorkflowCombinedApi
from EndToEndTester.utilities import loadFileJson, loadJson, getConfig, getUTCnow, timestampToDate
from EndToEndTester.utilities import moveFile, getLogger, setSenseEnv, checkCreateDir, refreshConfig, renameFile
from EndToEndTester.DBBackend import dbinterface


# Loops via all files and records them inside database;
# Identifies if it is final state (if create/delete is final ok - then final:
#   a) if final - move to archived dir (based on date) update record in db
#   b) if not final - keep it as lock - check if sense-o uuid is gone
#         if gone - move to archived dir and update record in db
#         if not gone - keep it as lock.
# after 12hr - move file to archived dir and update record in db


class Archiver:
    # pylint: disable=no-member
    """Archiver class - checks if file can be archived and it is final state"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.workflowApi = WorkflowCombinedApi()
        self.senseouuid = ""
        self.senseodata = {}
        self.senseoexc = None

    def _checkfinal(self):
        """Check if it reached final state"""
        return bool(self.requestentry.get("finalstate", 0))

    def _checkpathfindissue(self):
        """Check if there was path issue identified"""
        return bool(self.requestentry.get("pathfindissue", 0))

    def getsenseodata(self):
        """Get data from SENSE-O"""
        if self.senseouuid == self.requestentry["uuid"]:
            return self.senseodata, self.senseoexc
        self.senseouuid = self.requestentry["uuid"]
        self.senseoexc = None
        try:
            status = self.workflowApi.instance_get_status(
                si_uuid=self.requestentry["uuid"], verbose=True
            )
            self.senseodata = status
            self.senseoexc = ""
            return status, ""
        except Exception as ex:
            self.senseodata = {}
            self.senseoexc = ex
            return {}, ex

    def _checksenseomissing(self):
        """Check if si-uuid exists in sense-o"""
        self.workflowApi.si_uuid = None
        try:
            status, errmsg = self.getsenseodata()
            if status:
                self.logger.info(
                    "Instance still inside SENSE-O. Will not archive file (also means this pair will not get new request)"
                )
                self.logger.info(status)
            if errmsg:
                raise Exception from errmsg
        except Exception as ex:
            if "NOT_FOUND" in str(ex):
                return True
            self.logger.error(
                f"Received not understood exception from SENSE-O: {str(ex)}"
            )
        return False

    def _deleteSenseO(self, expired=True):
        """Delete from SENSE-O an instance. Done in the following scenarios:
        a) Instance failed due to path finding failure
        b) Request expired after timeout."""
        delete = False
        if self._checkpathfindissue() and not self._checksenseomissing():
            delete = True
        if not self._checksenseomissing() and expired:
            delete = True
        if delete:
            try:
                self.workflowApi.instance_delete(si_uuid=self.requestentry["uuid"])
            except Exception as ex:
                self.logger.error(f"Received an exception from SENSE-O: {str(ex)}")

    def _checkExpiredArchive(self):
        """Check if file is expired and should be archived"""
        # If file is not final and not path finding issue - check if it is expired
        # If expired - move file to archive and update db record
        # OKARCHIVE
        self.logger.info(
            f"Checking if file is expired (3days in OKARCHIVE): {self.requestentry['uuid']}"
        )
        self.logger.info(
            f'cancel final state: {self.data.get("cancel", {}).get("finalstate", "")}'
        )
        if not self.data.get("cancel", {}) or not self.data.get("cancel", {}).get(
            "finalstate", ""
        ):
            # We have no record information on finalstate. checking sense-o
            senseodata, exc = self.getsenseodata()
            if exc:
                self.logger.error(
                    f"Got an exception receiving data from SENSE-O: {str(exc)}"
                )
                if "Returned code 404" in str(exc) and "was not found" in str(exc):
                    return True
            elif (
                senseodata["superState"] == "CANCEL"
                and senseodata["subState"] == "READY"
                and senseodata["configState"] == "STABLE"
                and senseodata["archived"]
                and not senseodata["locked"]
            ):
                self.logger.info(
                    f'{self.requestentry["uuid"]} is in correct state to be removed. Checking time'
                )
                if getUTCnow() - self.requestentry["insertdate"] >= 259200:  # 3 days
                    return True
        elif self.data.get("cancel", {}).get("finalstate", "") == "OKARCHIVE":
            if getUTCnow() - self.requestentry["insertdate"] >= 259200:  # 3 days
                return True
        return False

    def _movefile(self, dbdone=False):
        """Move file to archived directory"""
        if dbdone:
            fname = os.path.basename(self.requestentry["fileloc"])
            newFName = f"{fname}.dbdone"
            archiveddir = self.config["workdir"]
            newFName = renameFile(self.requestentry["fileloc"], archiveddir, newFName)
        else:
            archiveddir = os.path.join(
                self.config["workdir"],
                "archived",
                timestampToDate(self.requestentry["insertdate"]),
            )
            newFName = moveFile(self.requestentry["fileloc"], archiveddir)
        return newFName

    def runArchiver(self):
        """Run Archiver and check if it should be archived"""
        # 1 check if finalstate - if it is  - move file, update db record;
        # 2. check if fialure was path finding - if so, move file, update db record;
        # 3. If not final state and not path finding issue - check if item remains in sense-o
        #     a) if remains - keep it as is - as this is our kind of lock file not to resubmit path request
        #     b) if gone - move file, update db record;
        newFName = None
        if self._checkfinal():
            self.logger.info("Request state is final. Moving file to archived.")
            newFName = self._movefile()
        elif self._checkpathfindissue():
            self.logger.info(
                "Request failed due to path finding. Moving file to archived."
            )
            newFName = self._movefile()
            self._deleteSenseO()
        elif self._checksenseomissing():
            self.logger.info(
                "Request deleted manually by admins from SENSE-O. Means we can restart scans. Moving file to archived."
            )
            newFName = self._movefile()
        elif self._checkExpiredArchive():
            self.logger.info("Request expired. Moving file to archived.")
            newFName = self._movefile()
            self._deleteSenseO(expired=True)
        # Check if newFName is set - if so - we update DB Record with new location
        if newFName:
            self.updaterequest(newFName)
            return True
        # DB Record entered into database, so we move file as .json.dbdone
        if not self.requestentry["fileloc"].endswith(".dbdone"):
            self._movefile(dbdone=True)
            self.updaterequest(newFName)
        return False


class DBRecorder:
    # pylint: disable=no-member
    """Handles database recording operations for requests, actions, verifications, and states."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db = dbinterface()
        self.dbdone = False

    def writerequest(self):
        """Record request"""
        dbentry = self.db.get(
            "requests", limit=1, search=[["uuid", self.requestentry["uuid"]]]
        )
        if not dbentry:
            self.db.insert("requests", [self.requestentry])

    def updaterequest(self, newFName):
        """Update Request and set new file location"""
        dbentry = self.db.get(
            "requests", limit=1, search=[["uuid", self.requestentry["uuid"]]]
        )
        if not dbentry:
            self.logger.error(
                f"Not sure what to update. this {self.requestentry['uuid']} not present in database"
            )
            return
        self.db.update(
            "requests",
            [
                {
                    "updatedate": getUTCnow(),
                    "fileloc": newFName,
                    "uuid": self.requestentry["uuid"],
                }
            ],
        )

    def writeactions(self):
        """Record actions"""
        for action in self.actionsentries:
            searchparams = [["uuid", action["uuid"]], ["action", action["action"]]]
            dbentry = self.db.get("actions", search=searchparams)
            if not dbentry:
                self.db.insert("actions", [action])

    def writeverification(self):
        """Record verification"""
        for verentry in self.verificationentries:
            searchparams = [
                [key, value]
                for key, value in verentry.items()
                if key not in ["insertdate", "updatedate"]
            ]
            dbentry = self.db.get("verification", search=searchparams)
            if not dbentry:
                self.db.insert("verification", [verentry])

    def writerequeststate(self):
        """Record request state"""
        for reqentry in self.requeststateentries:
            searchparams = [
                [key, value]
                for key, value in reqentry.items()
                if key not in ["totaltime", "entertime", "insertdate", "updatedate"]
            ]
            dbentry = self.db.get("requeststates", search=searchparams)
            if not dbentry:
                self.db.insert("requeststates", [reqentry])

    def writerunnerinfo(self, data):
        """Write worker status. Insert if no entries, update if diff"""
        searchkeys = [
            "alive",
            "totalworkers",
            "totalqueue",
            "remainingqueue",
            "starttime",
            "nextrun",
            "lockedrequests",
        ]
        searchparams = [[key, data[key]] for key in searchkeys]
        dbentry = self.db.get("runnerinfo", limit=1, search=searchparams)
        if dbentry:
            # Data is present and already matches in database
            return
        dbentry = self.db.get("runnerinfo", limit=1)
        if dbentry:
            data["id"] = dbentry[0]["id"]
            self.db.update("runnerinfo", [data])
        else:
            self.db.insert("runnerinfo", [data])

    def writelockedinfo(self, data):
        """Write all locked requests"""
        dbentry = self.db.get(
            "lockedrequests", limit=1, search=[["uuid", data["uuid"]]]
        )
        if not dbentry:
            self.db.insert("lockedrequests", [data])

    def writepingresults(self):
        """Write Ping results"""
        for ping in self.pingresults:
            searchparams = [
                [key, value]
                for key, value in ping.items()
                if key not in ["insertdate", "updatedate"]
            ]
            dbentry = self.db.get("pingresults", search=searchparams)
            if not dbentry:
                self.db.insert("pingresults", [ping])

    def getlockedinfo(self):
        """Get Locked info requests"""
        dbout = self.db.get("lockedrequests", limit=1000)
        return dbout

    def deletelockedinfo(self, data):
        """Delete Locked info request"""
        dbentry = self.db.get(
            "lockedrequests", limit=1, search=[["uuid", data["uuid"]]]
        )
        if dbentry:
            self.db.delete("lockedrequests", [["uuid", data["uuid"]]])


# pylint: disable=too-many-instance-attributes
class FileParser(DBRecorder, Archiver):
    """Parses files, extracts data, and records information into the database."""

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.lastconfigfetch = getUTCnow()
        self.logger = getLogger(
            name="DBRecorder", logFile="/var/log/EndToEndTester/DBRecorder.log"
        )
        self.requestentry = {}
        self.actionsentries = []
        self.verificationentries = []
        self.requeststateentries = []
        self.pingresults = []
        self.lockedfiles = []
        self.newpingentry = {}
        self.data = {}
        self.fname = {}
        self.db = dbinterface()
        # Default vals if not specified by hasNetworkStatus
        # create, verified - activated
        # create, unverified - create-unverified
        # cancel, verified - deactivated
        # cancel, unverified - deactivate-error
        self.defaultvals = {
            "create-verified": "activated",
            "create-unverified": "create-unverified",
            "modifycreate-verified": "activated",
            "modifycreate-unverified": "modify-unverified",
            "reprovision-verified": "activated",
            "reprovision-unverified": "reprovision-unverified",
            "modify-verified": "activated",
            "modify-unverified": "modify-unverified",
            "cancel-verified": "deactivated",
            "cancel-unverified": "cancel-unverified",
            "cancelrep-verified": "deactivated",
            "cancelrep-unverified": "cancel-unverified",
            "cancelarch-verified": "deactivated",
            "cancelarch-unverified": "cancel-unverified",
        }

    def _cleanup(self):
        """Clean up variables"""
        self.requestentry = {}
        self.actionsentries = []
        self.verificationentries = []
        self.requeststateentries = []
        self.data = {}
        self.fname = {}
        self.newpingentry = {}

    def _getSiteName(self, pairval):
        """Get Sitename of pair (or override from config)"""
        if self.config.get("entriessitename", ""):
            return self.config.get("entriessitename")
        site = self.config.get("entries", {}).get(pairval, {}).get("site", "UNKNOWN")
        return site

    def _forceRefreshConfig(self, pair):
        """Get Sitename - it might overrite config, if Sitename is unknown, or refresh once a day"""
        if self.lastconfigfetch >= self.lastconfigfetch + 86400:
            self.logger.debug(f"Last config refresh was at: {self.lastconfigfetch}")
            self.logger.info(
                "Forced config refresh - as last time we got it was 1 day ago"
            )
            self.config = refreshConfig(self.config)
            self.lastconfigfetch = getUTCnow()
        # If sitename is unknown, we check and refresh config every 1hr
        if (
            self._getSiteName(pair[0]) == "UNKNOWN"
            or self._getSiteName(pair[1]) == "UNKNOWN"
        ):
            self.logger.info(
                f"{self.requestentry['uuid']} got unknown sitename. Will force config refresh if older than 1hr"
            )
            if self.lastconfigfetch >= self.lastconfigfetch + 3600:
                self.logger.debug(f"Last config refresh was at: {self.lastconfigfetch}")
                self.logger.info("Forced config refresh due to unknown site")
                self.config = refreshConfig(self.config)
                self.lastconfigfetch = getUTCnow()

    def recordinfo(self):
        """Identify request information"""
        pair = self.data.get("info", {}).get("pair", [])
        if not pair or len(pair) != 2:
            raise ValueError(f"Invalid pair information for {self.fname}")
        uuid = self.data.get("info", {}).get("uuid", "")
        if not uuid:
            raise ValueError(f"Invalid uuid information for {self.fname}")
        self.requestentry["uuid"] = uuid
        self._forceRefreshConfig(
            pair
        )  # Force refresh if sitename unknown or 24hr passed.
        self.requestentry["port1"] = pair[0]
        self.requestentry["port2"] = pair[1]
        self.requestentry["site1"] = self._getSiteName(pair[0])
        self.requestentry["site2"] = self._getSiteName(pair[1])
        self.requestentry["fileloc"] = self.fname
        self.requestentry["insertdate"] = self.data.get("info", {}).get(
            "time", getUTCnow()
        )
        self.requestentry["updatedate"] = self.data.get("info", {}).get(
            "time", getUTCnow()
        )
        self.requestentry["requesttype"] = self.data.get("info", {}).get(
            "requesttype", "UNSET"
        )
        self.requestentry["failure"] = self.identifyerrors()
        self.requestentry["finalstate"] = (
            self.identifyfinalstate()
        )  # 0 - not final, 1 - final
        self.requestentry["pathfindissue"] = self.identifyPathFindIssue()
        self.requestentry["vlan"] = self.data["info"]["req"]["data"]["connections"][0][
            "terminals"
        ][0]["vlan_tag"]

    def identifyfinalstate(self):
        """Identify request information"""
        finalstate = 0
        if (
            self.data.get("create", {}).get("finalstate", "") == "OK"
            and self.data.get("cancel", {}).get("finalstate", "") == "OK"
        ):
            finalstate = 1
        else:
            self.logger.info(f"({self.requestentry['uuid']}) Not final state.")
            self.logger.info(
                f"({self.requestentry['uuid']}) create: {self.data.get('create', {}).get('finalstate', '')}"
            )
            self.logger.info(
                f"({self.requestentry['uuid']}) cancel: {self.data.get('cancel', {}).get('finalstate', '')}"
            )
        return finalstate

    def identifyPathFindIssue(self):
        """Identify if there was a path finding issue"""
        if "cannot find feasible path for connection" in self.requestentry["failure"]:
            return 1
        return 0

    def identifyerrors(self):
        """Identify errors from information"""
        errmsg = ""
        for key, lookup in {
            "ERROR": "error",
            "VALIDATION": "validation-error",
            "MANIFEST": "manifest-error",
        }.items():
            if lookup in self.data.get("create", {}):
                errmsg += f"{key}_CREATE: " + self.data.get("create", {}).get(
                    lookup, ""
                )
            if lookup in self.data.get("cancel", {}):
                errmsg += f"{key}_CANCEL: " + self.data.get("create", {}).get(
                    lookup, ""
                )
        return errmsg

    def recordactions(self):
        """Identify request information"""
        for key, val in self.data.get("timings", {}).items():
            action = {
                "uuid": self.requestentry["uuid"],
                "action": key,
                "insertdate": val["starttime"],
                "updatedate": val["starttime"],
                "site1": self.requestentry["site1"],
                "site2": self.requestentry["site2"],
            }
            self.actionsentries.append(action)

    def _identifyNetworkStatus(self, inputVal, key):
        """Record all sites it went through"""
        # pylint: disable=too-many-nested-blocks
        netstat = []
        for ckey, cval in inputVal.get(key, {}).items():
            if ckey.endswith("hasNetworkStatus"):
                for netdict in cval:
                    if netdict.get("value") and netdict.get("value") in inputVal:
                        for nkey, nval in inputVal[netdict["value"]].items():
                            if nkey.endswith("value"):
                                for netstatus in nval:
                                    if netstatus.get("value"):
                                        netstat.append(netstatus.get("value"))
        return netstat

    def _recordIdentifySites(self, inputVal, checkkey):
        """Record all sites it went through"""
        output = {}
        for key in inputVal.keys():
            for mapkey, mapsite in self.config.get("mappings", {}).items():
                if key.startswith(mapkey):
                    netstat = self._identifyNetworkStatus(inputVal, key)
                    if netstat or checkkey.startswith("cancel"):
                        output.setdefault(mapkey, [])
                        output[mapkey].append({"site": mapsite, "netstat": netstat})
                        break
        return output

    def _filternetstats(self, inputVal, defaultstatus):
        """Filter out netstats of equal entries"""
        output = []
        site = ""
        for netstat in inputVal:
            if netstat["site"] != site:
                site = netstat["site"]
            if "netstat" not in netstat:
                if defaultstatus not in output:
                    output.append(defaultstatus)
                continue
            if len(netstat["netstat"]) == 0:
                if defaultstatus not in output:
                    output.append(defaultstatus)
                continue
            for stat in netstat["netstat"]:
                if stat not in output:
                    output.append(stat)
        return output, site

    def recordverification(self):
        """Identify request information"""
        # This part is most fun to loop over all verification info and prepare database entries
        # do this for create and verified additions
        output = {}
        for key in [
            "create",
            "modifycreate",
            "cancelrep",
            "reprovision",
            "modify",
            "cancel",
            "cancelarch",
        ]:
            if key not in self.data:
                continue
            output.setdefault(key, {"verified": {}, "unverified": {}})
            # Load all verified, unverivied parts
            tmpdata = loadJson(
                self.data.get(key, {}).get("validation", {}).get("additionVerified", {})
            )
            output[key]["verified"].update(self._recordIdentifySites(tmpdata, key))
            tmpdata = loadJson(
                self.data.get(key, {})
                .get("validation", {})
                .get("additionUnverified", {})
            )
            output[key]["unverified"].update(self._recordIdentifySites(tmpdata, key))
            tmpdata = loadJson(
                self.data.get(key, {})
                .get("validation", {})
                .get("reductionVerified", {})
            )
            output[key]["verified"].update(self._recordIdentifySites(tmpdata, key))
            tmpdata = loadJson(
                self.data.get(key, {})
                .get("validation", {})
                .get("reductionUnverified", {})
            )
            output[key]["unverified"].update(self._recordIdentifySites(tmpdata, key))

        for key, val in output.items():
            for key1, val1 in val.items():
                for ckey, cval in val1.items():
                    # Identify all final network status
                    # Need to pass defaultstatus - based on keys
                    if not self.defaultvals.get(f"{key}-{key1}"):
                        self.logger.debug(
                            f"({self.requestentry['uuid']}) No default value for {key}-{key1}"
                        )
                        continue
                    netstatus, site = self._filternetstats(
                        cval, self.defaultvals[f"{key}-{key1}"]
                    )
                    if len(netstatus) == 0:
                        self.logger.debug(
                            f"({self.requestentry['uuid']}) No network status for {key}-{key1}-{ckey}-{site}"
                        )
                        continue
                    if not site:
                        self.logger.debug(
                            f"({self.requestentry['uuid']}) No site for {key}-{key1}-{ckey}"
                        )
                        continue
                    errmsg = ""
                    for netstat in netstatus:
                        if netstat != self.defaultvals[f"{key}-{key1}"]:
                            errmsg += f"{site} {ckey} Network status: {netstat}, "
                        item = {
                            "uuid": self.requestentry["uuid"],
                            "action": key,
                            "netstatus": netstat,
                            "site": site,
                            "urn": ckey,
                            "verified": 1 if key1 == "verified" else 0,
                            "site1": self.requestentry["site1"],
                            "site2": self.requestentry["site2"],
                            "insertdate": self.requestentry["insertdate"],
                            "updatedate": self.requestentry["updatedate"],
                        }
                        self.verificationentries.append(item)
                    if errmsg:
                        self.requestentry["failure"] = (
                            errmsg + self.requestentry["failure"]
                        )

    def _calculateTotalTime(self, tmplist):
        """Calculate total time to transition from one state to another"""
        # 1. Need to define all correct states what state goes to what
        configstates = [
            "create",
            "UNKNOWN",
            "PENDING",
            "SCHEDULED",
            "UNSTABLE",
            "STABLE",
        ]
        createstates = [
            "CREATE%screate",
            "CREATE - PENDING%screate",
            "CREATE - COMPILED%screate",
            "CREATE - PROPAGATED%screate",
            "CREATE - COMMITTING%screate",
            "CREATE - COMMITTED%screate",
            "CREATE - READY%screate",
            "CREATE - FAILED%screate",
            "CREATE%smodifycreate",
            "MODIFY - PENDING%smodifycreate",
            "MODIFY - COMPILED%smodifycreate",
            "MODIFY - PROPAGATED%smodifycreate",
            "MODIFY - COMMITTING%smodifycreate",
            "MODIFY - COMMITTED%smodifycreate",
            "MODIFY - READY%smodifycreate",
            "MODIFY - FAILED%smodifycreate",
            "CREATE%smodifycreate",
            "CREATE - PENDING%smodifycreate",
            "CREATE - COMPILED%smodifycreate",
            "CREATE - PROPAGATED%smodifycreate",
            "CREATE - COMMITTING%smodifycreate",
            "CREATE - COMMITTED%smodifycreate",
            "CREATE - READY%smodifycreate",
            "CREATE - FAILED%smodifycreate",
            "CREATE%scancelrep",
            "CANCEL - PENDING%scancelrep",
            "CANCEL - COMPILED%scancelrep",
            "CANCEL - PROPAGATED%scancelrep",
            "CANCEL - COMMITTING%scancelrep",
            "CANCEL - COMMITTED%scancelrep",
            "CANCEL - READY%scancelrep",
            "CANCEL - FAILED%scancelrep",
            "CREATE%sreprovision",
            "REINSTATE - PENDING%sreprovision",
            "REINSTATE - COMPILED%sreprovision",
            "REINSTATE - PROPAGATED%sreprovision",
            "REINSTATE - COMMITTING%sreprovision",
            "REINSTATE - COMMITTED%sreprovision",
            "REINSTATE - READY%sreprovision",
            "REINSTATE - FAILED%sreprovision",
            "CREATE%smodify",
            "MODIFY - PENDING%smodify",
            "MODIFY - COMPILED%smodify",
            "MODIFY - PROPAGATED%smodify",
            "MODIFY - COMMITTING%smodify",
            "MODIFY - COMMITTED%smodify",
            "MODIFY - READY%smodify",
            "MODIFY - FAILED%smodify",
            "REINSTATE - READY%smodify",
            "REINSTATE - FAILED%smodify",
            "CREATE%scancel",
            "CANCEL - PENDING%scancel",
            "CANCEL - COMPILED%scancel",
            "CANCEL - PROPAGATED%scancel",
            "CANCEL - COMMITTING%scancel",
            "CANCEL - COMMITTED%scancel",
            "CANCEL - READY%scancel",
            "CANCEL - FAILED%scancel",
            "CREATE%scancelarch",
            "CANCEL - PENDING%scancelarch",
            "CANCEL - COMPILED%scancelarch",
            "CANCEL - PROPAGATED%scancelarch",
            "CANCEL - COMMITTING%scancelarch",
            "CANCEL - COMMITTED%scancelarch",
            "CANCEL - READY%scancelarch",
            "CANCEL - FAILED%scancelarch",
        ]
        lasttimestamp = 0
        firststart = 0
        for stfind in createstates:
            for configstate in configstates:
                findstate = stfind.replace("%s", configstate)
                # loop via index via tmplist
                total = len(tmplist)
                counter = 0
                while counter < total:
                    fullstate = (
                        tmplist[counter]["state"]
                        + tmplist[counter]["configstate"]
                        + tmplist[counter]["action"]
                    )
                    if fullstate == findstate:
                        # pop item from list
                        item = tmplist.pop(counter)
                        if lasttimestamp == 0:
                            lasttimestamp = item["entertime"]
                            firststart = item["entertime"]
                        else:
                            # This is the diff time spent in previous state.
                            diff = item["entertime"] - lasttimestamp
                            self.requeststateentries[-1]["totaltime"] = (
                                diff if diff > 0 else 0
                            )
                            self.requeststateentries[-1]["sincestart"] = (
                                item["entertime"] - firststart
                            )
                            lasttimestamp = item["entertime"]
                            self.logger.info(
                                f"({self.requestentry['uuid']}) Found state transition: {item['state']} - {item['configstate']} - {item['action']} - {diff}. Since start: {item['entertime'] - firststart}"
                            )
                        self.requeststateentries.append(item)
                        counter = total
                    counter += 1
        # If we still have entries remaining here, we need to loop via them and add
        for item in tmplist:
            self.logger.info(f"Was not able to identify state transition for: {item}")
            self.requeststateentries.append(item)

        # 2. Loop via all items and see if we can find the next state
        # 3. If we find the next state - we need to calculate time difference from entertime to next state

    def recordrequeststate(self):
        """Identify request information"""
        tmplist = []
        for key, val in self.data.get("timings", {}).items():
            for key1, val1 in val.items():
                if not isinstance(val1, dict):
                    continue
                for ckey, cval in val1.get("configStatus", {}).items():
                    item = {
                        "uuid": self.requestentry["uuid"],
                        "action": key,  # create, cancel, cancelrep...
                        "state": key1,  # CANCEL - READY ...
                        "configstate": ckey,  # STABLE, UNSTABLE...
                        "entertime": cval,
                        "site1": self.requestentry["site1"],
                        "site2": self.requestentry["site2"],
                        "totaltime": 0,  # This will be updated later
                        "sincestart": 0,  # This will be updated later
                        "insertdate": self.requestentry["insertdate"],
                        "updatedate": self.requestentry["updatedate"],
                    }
                    tmplist.append(item)
        # Now we need to calculate total time for each entry
        self._calculateTotalTime(tmplist)

    def _parsepingstdout(self, line):
        """Parse a line containing ping results and set output values."""
        # Parse transmitted and received packets
        transmittedRe = re.search(r"(\d+)\s+packets transmitted", line)
        receivedRe = re.search(r"(\d+)\s+received", line)
        if transmittedRe:
            self.newpingentry["transmitted"] = int(transmittedRe.group(1))
        if receivedRe:
            self.newpingentry["received"] = int(receivedRe.group(1))
        # Parse packet loss
        packetlossRe = re.search(r"(\d+(\.\d+)?)% packet loss", line)
        if packetlossRe:
            self.newpingentry["packetloss"] = float(packetlossRe.group(1))
        # Parse RTT values (min/avg/max/mdev)
        rttRe = re.search(
            r"rtt min/avg/max/mdev = ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)", line
        )
        if rttRe:
            self.newpingentry["rttmin"] = float(rttRe.group(1))
            self.newpingentry["rttavg"] = float(rttRe.group(2))
            self.newpingentry["rttmax"] = float(rttRe.group(3))
            self.newpingentry["rttmdev"] = float(rttRe.group(4))

    def __resetpingentry(self):
        """Reset ping entry"""
        self.newpingentry = {
            "uuid": self.requestentry["uuid"],
            "site1": self.requestentry["site1"],
            "site2": self.requestentry["site2"],
            "action": "",
            "insertdate": self.requestentry["insertdate"],
            "updatedate": self.requestentry["updatedate"],
            "port1": self.requestentry["port1"],
            "port2": self.requestentry["port2"],
            "ipto": "",
            "ipfrom": "",
            "failed": 0,
            "transmitted": 0,
            "received": 0,
            "packetloss": 0.0,
            "rttmin": 0.0,
            "rttavg": 0.0,
            "rttmax": 0.0,
            "rttmdev": 0.0,
        }

    def recordpingresults(self, action):
        """Identify ping results information"""
        for item in (
            self.data.get(action, {})
            .get("pingresults", {})
            .get("final", {})
            .get("results", [])
        ):
            self.__resetpingentry()
            self.newpingentry["action"] = action
            output = loadJson(item.get("output", "{}"))
            # load requestdict and get ipto
            requestdict = loadJson(item.get("requestdict", "{}"))
            # get ipfrom
            self.newpingentry["ipto"] = requestdict.get("ip", "")
            ipfrom = "unknown"
            if requestdict["hostname"] in self.data.get(action, {}).get(
                "pingresults", {}
            ).get("submit", {}).get("hostips", {}):
                ipfrom = self.data[action]["pingresults"]["submit"]["hostips"][
                    requestdict["hostname"]
                ]
            self.newpingentry["ipfrom"] = ipfrom
            # Identify vlan from request
            self.newpingentry["vlanfrom"] = "any"
            self.newpingentry["vlanto"] = "any"
            if self.newpingentry["ipto"] in self.data.get(action, {}).get(
                "pingresults", {}
            ).get("submit", {}).get("ipvlans", {}):
                self.newpingentry["vlanto"] = self.data[action]["pingresults"][
                    "submit"
                ]["ipvlans"][self.newpingentry["ipto"]]
            if self.newpingentry["ipfrom"] in self.data.get(action, {}).get(
                "pingresults", {}
            ).get("submit", {}).get("ipvlans", {}):
                self.newpingentry["vlanfrom"] = self.data[action]["pingresults"][
                    "submit"
                ]["ipvlans"][self.newpingentry["ipfrom"]]
            # parse the stdout
            for line in output.get("stdout", []):
                self._parsepingstdout(line)
            # Identify if ping failed
            if self.newpingentry["transmitted"] == 0:
                self.newpingentry["failed"] = 1
            if self.newpingentry["received"] == 0:
                self.newpingentry["failed"] = 1
            if self.newpingentry["packetloss"] > 0.0:
                self.newpingentry["failed"] = 1
            self.pingresults.append(self.newpingentry)

    def writedata(self):
        """Write data to DB"""
        if self.dbdone:
            self.logger.info(
                f"({self.requestentry['uuid']}) DB Done file. Will not write to db again."
            )
        else:
            self.writerequest()
            self.writeactions()
            self.writeverification()
            self.writerequeststate()
            self.writepingresults()

    def recorddata(self):
        """Identify request information"""
        self.recordinfo()
        self.recordactions()
        self.recordverification()
        self.recordrequeststate()
        for key in ["create", "reprovision", "modify", "modifycreate"]:
            self.recordpingresults(key)

    def checkrunnerinfo(self):
        """Record worker status inside database"""
        # Report status of tester runner
        statusout = loadFileJson(
            os.path.join(self.config["workdir"], "testerinfo" + ".run")
        )
        if not statusout:
            self.logger.warning(
                "Did not receive status information of thread worker. Will not write to db"
            )
            return
        timenow = getUTCnow()
        statusout["lockedrequests"] = len(self.lockedfiles)
        statusout["insertdate"] = timenow
        statusout["updatedate"] = timenow
        self.writerunnerinfo(statusout)

    def checklockedrequests(self):
        """Check all locked requests"""
        # Get all locked requests from DB;
        alllocked = {}
        for item in self.getlockedinfo():
            alllocked[item["uuid"]] = item
        # For each in self.lockedfiles - check if uuid exists in db output
        for item in self.lockedfiles:
            if item["uuid"] in alllocked:
                del alllocked[item["uuid"]]
            else:
                self.writelockedinfo(item)
        # If we have any locked remaining here - we delete them - means lock is gone;
        self.getlockedinfo()
        for key, val in alllocked.items():
            self.logger.info(
                f"The following lock file gone. Removing from locked db {key}"
            )
            self.deletelockedinfo(val)

    def main(self):
        """Main Run loop all json run output"""
        # loop current directory files and load json
        self.lockedfiles = []
        checkCreateDir(self.config["workdir"])
        for file in os.listdir(self.config["workdir"]):
            self.dbdone = False
            self.data = {}
            self.fname = None
            if file.endswith(".json") or file.endswith(".dbdone"):
                fullpath = os.path.join(self.config["workdir"], file)
                # Check if lock file present, means running now
                if os.path.exists(fullpath + ".lock"):
                    self.logger.info(
                        f"FileLock for {fullpath} exists. Means run ongoing"
                    )
                    continue
                if fullpath.endswith(".dbdone"):
                    self.dbdone = True
                self.logger.info(f"Checking file: {fullpath}")
                self._cleanup()
                self.fname = fullpath
            if self.fname:
                self.data = loadFileJson(self.fname)
            if self.data:
                try:
                    self.recorddata()
                    self.writedata()
                    if not self.runArchiver():
                        self.lockedfiles.append(self.requestentry)
                except Exception as ex:
                    self.logger.error(f" Error: {ex}")
                    self.logger.error("-" * 40)
        try:
            self.checklockedrequests()
        except Exception as ex:
            self.logger.error(f" Error: {ex}")
            self.logger.error("-" * 40)
        try:
            self.checkrunnerinfo()
        except Exception as ex:
            self.logger.error(f" Error: {ex}")
            self.logger.error("-" * 40)


if __name__ == "__main__":
    mainconf = getConfig()
    setSenseEnv(mainconf)
    runner = FileParser(mainconf)
    runner.main()
