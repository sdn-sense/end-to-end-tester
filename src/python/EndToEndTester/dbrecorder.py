#!/usr/bin/env python3
"""DB Backend for communication with database. Mainly we use mariadb
Title                   : end-to-end-tester
Author                  : Justas Balcas
Email                   : jbalcas (at) es.net
@Copyright              : Copyright (C) 2025 ESnet
Date                    : 2025/03/14
"""
import os
from sense.client.workflow_combined_api import WorkflowCombinedApi
from EndToEndTester.utilities import loadFileJson, loadJson, getConfig, getUTCnow, timestampToDate, moveFile, getLogger, setSenseEnv, checkCreateDir
from EndToEndTester.DBBackend import dbinterface


# Loops via all files and records them inside database;
# Identifies if it is final state (if create/delete is final ok - then final:
#   a) if final - move to archived dir (based on date) update record in db
#   b) if not final - keep it as lock - check if sense-o uuid is gone
#         if gone - move to archived dir and update record in db
#         if not gone - keep it as lock.
# after 12hr - move file to archived dir and update record in db

class Archiver():
    # pylint: disable=no-member
    """Archiver class - checks if file can be archived and it is final state"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.workflowApi = WorkflowCombinedApi()

    def _checkfinal(self):
        """Check if it reached final state"""
        return bool(self.requestentry.get('finalstate', 0))

    def _checkpathfindissue(self):
        """Check if there was path issue identified"""
        return bool(self.requestentry.get('pathfindissue', 0))

    def _checksenseomissing(self):
        """Check if si-uuid exists in sense-o"""
        self.workflowApi.si_uuid = None
        try:
            status = self.workflowApi.instance_get_status(si_uuid=self.requestentry['uuid'], verbose=True)
            self.logger.info('Instance still inside SENSE-O. Will not archive file (also means this pair will not get new request)')
            self.logger.info(status)
        except Exception as ex:
            if 'NOT_FOUND' in str(ex):
                return True
            self.logger.error(f"Received not understood exception from SENSE-O: {str(ex)}")
        return False

    def _deleteSenseO(self):
        """Delete from SENSE-O an instance. Done in the following scenarios:
         a) Instance failed due to path finding failure"""
        if self._checkpathfindissue() and not self._checksenseomissing():
            try:
                self.workflowApi.instance_delete(si_uuid=self.requestentry['uuid'])
            except Exception as ex:
                self.logger.error(f"Received an exception from SENSE-O: {str(ex)}")


    def _movefile(self):
        """Move file to archived directory"""
        archiveddir = os.path.join(self.config['workdir'],
                                   'archived',
                                   timestampToDate(self.requestentry['insertdate']))
        newFName = moveFile(self.requestentry['fileloc'], archiveddir)
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
            self.logger.info('Request state is final. Moving file to archived.')
            newFName = self._movefile()
        elif self._checkpathfindissue():
            self.logger.info('Request failed due to path finding. Moving file to archived.')
            newFName = self._movefile()
            self._deleteSenseO()
        elif self._checksenseomissing():
            self.logger.info('Request deleted manually by admins from SENSE-O. Means we can restart scans. Moving file to archived.')
            newFName = self._movefile()
        # Check if newFName is set - if so - we update DB Record with new location
        if newFName:
            self.updaterequest(newFName)

class DBRecorder():
    # pylint: disable=no-member
    """Handles database recording operations for requests, actions, verifications, and states."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db = dbinterface()

    def writerequest(self):
        """Record request"""
        dbentry = self.db.get("requests", limit=1, search=[['uuid', self.requestentry['uuid']]])
        if not dbentry:
            self.db.insert("requests", [self.requestentry])

    def updaterequest(self, newFName):
        """Update Request and set new file location"""
        dbentry = self.db.get("requests", limit=1, search=[['uuid', self.requestentry['uuid']]])
        if not dbentry:
            self.logger.error(f"Not sure what to update. this {self.requestentry['uuid']} not present in database")
            return
        self.db.update("requests", [{"updatedate": getUTCnow(),
                                     "fileloc": newFName,
                                     "uuid": self.requestentry['uuid']}])

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
            searchparams = [[key, value] for key, value in verentry.items()]
            dbentry = self.db.get("verification", search=searchparams)
            if not dbentry:
                self.db.insert("verification", [verentry])

    def writerequeststate(self):
        """Record request state"""
        for reqentry in self.requeststateentries:
            searchparams = [[key, value] for key, value in reqentry.items()]
            dbentry = self.db.get("requeststates", search=searchparams)
            if not dbentry:
                self.db.insert("requeststates", [reqentry])

    def writeworkerstatus(self, data):
        """Write worker status. Insert if no entries, update if diff"""
        searchkeys = ['alive', 'totalworkers', 'totalqueue', 'remainingqueue', 'starttime', 'nextrun']
        searchparams = [[key, data[key]] for key in searchkeys]
        dbentry = self.db.get("workerstatus", limit=1, search=searchparams)
        if dbentry:
            # Data is present and already matches in database
            return
        dbentry = self.db.get("workerstatus", limit=1)
        if dbentry:
            data[id] = dbentry[0]
            self.db.update('workerstatus', [data])
        else:
            self.db.insert('workerstatus', [data])

# pylint: disable=too-many-instance-attributes
class FileParser(DBRecorder, Archiver):
    """Parses files, extracts data, and records information into the database."""
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.logger = getLogger(name='DBRecorder', logFile='/var/log/EndToEndTester/DBRecorder.log')
        self.requestentry = {}
        self.actionsentries = {}
        self.verificationentries = {}
        self.requeststateentries = {}
        self.data = {}
        self.fname = {}
        self.db = dbinterface()
        # Default vals if not specified by hasNetworkStatus
        # create, verified - activated
        # create, unverified - activate-error
        # cancel, verified - deactivated
        # cancel, unverified - deactivate-error
        self.defaultvals = {'create-verified': 'activated', 'create-unverified': 'activate-error',
                            'cancel-verified': 'deactivated', 'cancel-unverified': 'deactivate-error'}

    def _cleanup(self):
        """Clean up variables"""
        self.requestentry = {}
        self.actionsentries = []
        self.verificationentries = []
        self.requeststateentries = []
        self.data = {}
        self.fname = {}

    def recordinfo(self):
        """Identify request information"""
        pair = self.data.get('info', {}).get('pair', [])
        if not pair or len(pair) != 2:
            raise ValueError(f"Invalid pair iformation for {self.fname}")
        uuid = self.data.get('info', {}).get('uuid', '')
        if not uuid:
            raise ValueError(f"Invalid uuid iformation for {self.fname}")
        self.requestentry['port1'] = pair[0]
        self.requestentry['port2'] = pair[1]
        self.requestentry['uuid'] = uuid
        self.requestentry['site1'] = self.config.get("entries", {}).get(pair[0], "UNKNOWN")
        self.requestentry['site2'] = self.config.get("entries", {}).get(pair[1], "UNKNOWN")
        self.requestentry['fileloc'] = self.fname
        self.requestentry['insertdate'] = self.data.get('info', {}).get('time', getUTCnow())
        self.requestentry['updatedate'] = self.data.get('info', {}).get('time', getUTCnow())
        self.requestentry['failure'] = self.identifyerrors()
        self.requestentry['finalstate'] = self.identifyfinalstate() # 0 - not final, 1 - final
        self.requestentry['pathfindissue'] = self.identifyPathFindIssue()

    def identifyfinalstate(self):
        """Identify request information"""
        finalstate = 0
        if self.data.get('create', {}).get('finalstate', '') == 'OK' and \
           self.data.get('cancel', {}).get('finalstate', '') == 'OK':
            finalstate = 1
        else:
            self.logger.info(f"({self.requestentry['uuid']}) Not final state.")
            self.logger.info(f"({self.requestentry['uuid']}) create: {self.data.get('create', {}).get('finalstate', '')}")
            self.logger.info(f"({self.requestentry['uuid']}) cancel: {self.data.get('cancel', {}).get('finalstate', '')}")
        return finalstate

    def identifyPathFindIssue(self):
        """Identify if there was a path finding issue"""
        if "cannot find feasible path for connection" in self.requestentry['failure']:
            return 1
        return 0

    def identifyerrors(self):
        """Identify errors from information"""
        errmsg = ""
        if 'error' in self.data.get('create', {}):
            errmsg = 'CREATE: ' + self.data.get('create', {}).get('error', '')
        if 'error' in self.data.get('cancel', {}):
            errmsg += 'CANCEL: ' + self.data.get('cancel', {}).get('error', '')
        return errmsg

    def recordactions(self):
        """Identify request information"""
        for key, val in self.data.get('timings', {}).items():
            action = {'uuid': self.requestentry['uuid'],
                      'action': key,
                      'insertdate': val['starttime'],
                      'updatedate': val['starttime'],
                      'site1': self.requestentry['site1'],
                      'site2': self.requestentry['site2']}
            self.actionsentries.append(action)

    def _identifyNetworkStatus(self, inputVal, key):
        """Record all sites it went through"""
        netstat = []
        for ckey, cval in inputVal.get(key, {}).items():
            if ckey.endswith('hasNetworkStatus'):
                for netdict in cval:
                    if netdict.get('value'):
                        if netdict.get('value') in inputVal:
                            for nkey, nval in inputVal[netdict['value']].items():
                                if nkey.endswith('value'):
                                    for netstatus in nval:
                                        if netstatus.get('value'):
                                            netstat.append(netstatus.get('value'))
        return netstat


    def _recordIdentifySites(self, inputVal):
        """Record all sites it went through"""
        output = {}
        for key in inputVal.keys():
            found = False
            for mapkey, mapsite in self.config.get("mappings", {}).items():
                if key.startswith(mapkey):
                    netstat = self._identifyNetworkStatus(inputVal, key)
                    output.setdefault(mapkey, [])
                    output[mapkey].append({'site': mapsite, 'netstat': netstat})
                    found = True
                    break
            if not found:
                self.logger.debug(f"({self.requestentry['uuid']}) Unknown site: {key} - not found in mapping.")
        return output

    def _filternetstats(self, inputVal, defaultstatus):
        """Filter out netstats of equal entries"""
        output = []
        site = ""
        for netstat in inputVal:
            if netstat['site'] != site:
                site = netstat['site']
            if 'netstat' not in netstat:
                if defaultstatus not in output:
                    output.append(defaultstatus)
                continue
            if len(netstat['netstat']) == 0:
                if defaultstatus not in output:
                    output.append(defaultstatus)
                continue
            for stat in netstat['netstat']:
                if stat not in output:
                    output.append(stat)
        return output, site

    def recordverification(self):
        """Identify request information"""
        # This part is most fun to loop over all verification info and prepare database entries
        # do this for create and verified additions
        output = {'create': {'verified': {}, 'unverified': {}}, 'cancel': {'verified': {}, 'unverified': {}}}
        tmpdata = loadJson(self.data.get('create', {}).get('validation', {}).get('additionVerified', {}))
        output['create']['verified'] = self._recordIdentifySites(tmpdata)
        # do this for create and unverified additions
        tmpdata = loadJson(self.data.get('create', {}).get('validation', {}).get('additionUnverified', {}))
        output['create']['unverified'] = self._recordIdentifySites(tmpdata)
        # do this for cancel and verified reductions
        tmpdata = loadJson(self.data.get('cancel', {}).get('validation', {}).get('reductionVerified', {}))
        output['cancel']['verified'] = self._recordIdentifySites(tmpdata)
        # do this for cancel and unverified reductions
        tmpdata = loadJson(self.data.get('cancel', {}).get('validation', {}).get('reductionUnverified', {}))
        output['cancel']['unverified'] = self._recordIdentifySites(tmpdata)
        for key, val in output.items():
            for key1, val1 in val.items():
                for ckey, cval in val1.items():
                    # Identify all final network status
                    # Need to pass defaultstatus - based on keys
                    netstatus, site = self._filternetstats(cval, self.defaultvals[f"{key}-{key1}"])
                    if len(netstatus) == 0:
                        self.logger.debug(f"({self.requestentry['uuid']}) No network status for {key}-{key1}-{ckey}-{site}")
                        continue
                    if not site:
                        self.logger.debug(f"({self.requestentry['uuid']}) No site for {key}-{key1}-{ckey}")
                        continue
                    errmsg = ""
                    for netstat in netstatus:
                        if netstat != self.defaultvals[f"{key}-{key1}"]:
                            errmsg += f"{site} {ckey} Network status: {netstat}, "
                        item = {'uuid': self.requestentry['uuid'],
                                'action': key,
                                'netstatus': netstat,
                                'site': site,
                                'urn': ckey,
                                'verified': 1 if key1 == 'verified' else 0,
                                'site1': self.requestentry['site1'],
                                'site2': self.requestentry['site2'],
                                'insertdate': self.requestentry['insertdate'],
                                'updatedate': self.requestentry['updatedate']}
                        self.verificationentries.append(item)
                    if errmsg:
                        self.requestentry["failure"] = errmsg + self.requestentry["failure"]

    def recordrequeststate(self):
        """Identify request information"""
        for key, val in self.data.get('timings', {}).items():
            for key1, val1 in val.items():
                if not isinstance(val1, dict):
                    continue
                for ckey, cval in val1.get('configStatus', {}).items():
                    item = {'uuid': self.requestentry['uuid'],
                            'action': key,
                            'state': key1,
                            'configstate': ckey,
                            'entertime': cval,
                            'site1': self.requestentry['site1'],
                            'site2': self.requestentry['site2'],
                            'insertdate': self.requestentry['insertdate'],
                            'updatedate': self.requestentry['updatedate']}
                    self.requeststateentries.append(item)

    def writedata(self):
        """Write data to DB"""
        self.writerequest()
        self.writeactions()
        self.writeverification()
        self.writerequeststate()

    def recorddata(self):
        """Identify request information"""
        self.recordinfo()
        self.recordactions()
        self.recordverification()
        self.recordrequeststate()

    def checkworkerstatus(self):
        """Record worker status inside database"""
        # Report status of tester runner
        statusout = loadFileJson(os.path.join(self.config['workdir'], "testerinfo" + '.run'))
        timenow = getUTCnow()
        statusout['insertdate'] = timenow
        statusout['updatedate'] = timenow
        self.writeworkerstatus(statusout)

    def main(self):
        """Main Run loop all json run output"""
        # loop current directory files and load json
        checkCreateDir(self.config['workdir'])
        for file in os.listdir(self.config['workdir']):
            if file.endswith(".json"):
                fullpath = os.path.join(self.config['workdir'], file)
                # Check if lock file present, means running now
                if os.path.exists(fullpath + '.lock'):
                    self.logger.info(f"FileLock for {fullpath} exists. Means run ongoing")
                    continue
                self.logger.info(f"Checking file: {fullpath}")
                self._cleanup()
                self.fname = fullpath
                self.data = loadFileJson(self.fname)
                try:
                    self.recorddata()
                    self.writedata()
                    self.runArchiver()
                except Exception as ex:
                    self.logger.error(f" Error: {ex}")
                    self.logger.error('-'*40)
        try:
            self.checkworkerstatus()
        except Exception as ex:
            self.logger.error(f" Error: {ex}")
            self.logger.error('-'*40)


if __name__ == '__main__':
    mainconf = getConfig()
    setSenseEnv(mainconf)
    runner = FileParser(mainconf)
    runner.main()
