#!/usr/bin/env python3
# pylint: disable=line-too-long
"""Automatic testing of SENSE Endpoints.
Title                   : end-to-end-tester
Author                  : Justas Balcas
Email                   : jbalcas (at) es.net
@Copyright              : Copyright (C) 2025 ESnet
Date                    : 2025/03/14
"""
import os
import sys
import json
import time
import copy
import pprint
import threading
import random
import queue
import traceback
from itertools import combinations
from EndToEndTester.utilities import loadJson, dumpJson, getUTCnow, getConfig, checkCreateDir
from EndToEndTester.utilities import getLogger, setSenseEnv, dumpFileJson, timestampToDate
from EndToEndTester.utilities import fetchRemoteConfig, loadYaml, pauseTesting
from EndToEndTester.siterm import SiteRMApi
from sense.common import classwrapper
from sense.client.workflow_combined_api import WorkflowCombinedApi
from sense.client.workflow_phased_api import WorkflowPhasedApi
from sense.client.discover_api import DiscoverApi


requests = {
    "guaranteedCapped": {
        "service": "dnc",
        "alias": "REPLACEME",
        "data": {
            "type": "Multi-Path P2P VLAN",
            "connections": [
                {
                    "bandwidth": {"qos_class": "guaranteedCapped", "capacity": "2000"},
                    "name": "Connection 1",
                    "ip_address_pool": {
                        "netmask": "/64",
                        "name": "AutoGOLE-Test-IPv6-Pool",
                    },
                    "terminals": [
                        {
                            "vlan_tag": "REPLACEME",
                            "assign_ip": True,
                            "uri": "REPLACEME",
                        },
                        {
                            "vlan_tag": "REPLACEME",
                            "assign_ip": True,
                            "uri": "REPLACEME",
                        },
                    ],
                    "assign_debug_ip": True,
                }
            ],
        },
    },
    "bestEffort": {
        "service": "dnc",
        "alias": "REPLACEME",
        "data": {
            "type": "Multi-Path P2P VLAN",
            "connections": [
                {
                    "bandwidth": {"qos_class": "bestEffort"},
                    "name": "Connection 1",
                    "ip_address_pool": {
                        "netmask": "/64",
                        "name": "AutoGOLE-Test-IPv6-Pool",
                    },
                    "terminals": [
                        {
                            "vlan_tag": "REPLACEME",
                            "assign_ip": True,
                            "uri": "REPLACEME",
                        },
                        {
                            "vlan_tag": "REPLACEME",
                            "assign_ip": True,
                            "uri": "REPLACEME",
                        },
                    ],
                    "assign_debug_ip": True,
                }
            ],
        },
    },
}
net_request = {
    "nettest": {
        "service": "dnc",
        "alias": "REPLACEME",
        "data": {
            "type": "Multi-Path P2P VLAN",
            "connections": [
                {
                    "bandwidth": {"qos_class": "guaranteedCapped", "capacity": "2000"},
                    "name": "Connection 1",
                    "terminals": [
                        {
                            "vlan_tag": "REPLACEME",
                            "assign_ip": False,
                            "uri": "REPLACEME",
                        },
                        {
                            "vlan_tag": "REPLACEME",
                            "assign_ip": False,
                            "uri": "REPLACEME",
                        },
                    ],
                    "assign_debug_ip": False,
                }
            ],
        },
    }
}
l3_request = {
    "l3_request": {
        "data": {
            "type": "Site-L3 over P2P VLAN",
            "connections": [
                {
                    "bandwidth": {
                        "qos_class": "guaranteedCapped",
                        "capacity": "2000"
                    },
                    "name": "Connection 1",
                    "ip_address_pool": {
                        "netmask": "/64",
                        "name": "RUCIO-BGP-P2P-Slash64-Pool"
                    },
                    "terminals": [
                        {
                            "vlan_tag": "any",
                            "assign_ip": True,
                            "ipv6_prefix_list": "REPLACEME",
                            "uri": "REPLACEME"
                        },
                        {
                            "vlan_tag": "any",
                            "assign_ip": True,
                            "ipv6_prefix_list": "REPLACEME",
                            "uri": "REPLACEME"
                        }
                    ]
                }
            ]
        },
        "service": "dnc",
        "alias": "REPLACEME"
    }
}

def getFullTraceback(ex):
    """Get full traceback"""
    tracebackMsg = ""
    tracebackMsg += "Exception occurred:"
    tracebackMsg += f"\nType: {str(type(ex).__name__)}"
    tracebackMsg += f"\nMessage: {str(ex)}"
    tracebackMsg += "\nTraceback:\b"
    tracebackMsg += traceback.format_exc()
    return tracebackMsg


def timer_func(func):
    """Decorator function to calculate the execution time of a function"""

    def wrap_func(*args, **kwargs):
        t1 = getUTCnow()
        result = func(*args, **kwargs)
        t2 = getUTCnow()
        print(f"== Function {func.__name__!r} executed in {(t2 - t1):.4f}s")
        print(f"== Function {func.__name__!r} returned: {result}")
        print(f"== Function {func.__name__!r} args: {args}")
        print(f"== Function {func.__name__!r} kwargs: {kwargs}")
        return result

    return wrap_func


def getvlanrange(config):
    """Get VLAN range"""
    vlanrange = []
    if config.get("vlans", None):
        # vlans: [1779-1799. 3110-3139]
        for vlans in config.get("vlans", []):
            if "-" in vlans:
                try:
                    start, end = vlans.split("-")
                    start = int(start)
                    end = int(end)
                    if start > end:
                        raise ValueError(
                            f"VLAN range {vlans} is invalid. Start is greater than end."
                        )
                    vlanrange.extend([str(i) for i in range(start, end + 1)])
                except Exception as ex:
                    raise ValueError(
                        f"VLAN range {vlans} is invalid. Error: {ex}"
                    ) from ex
            else:
                vlanrange.append(vlans)
    else:
        vlanrange = ["any"]
    return vlanrange


@classwrapper
class SENSEWorker:
    """SENSE Worker class"""

    # pylint: disable=too-many-return-statements,too-many-instance-attributes,too-many-branches

    @timer_func
    def __init__(self, task_queue, workerid=0, config=None):
        self.task_queue = task_queue
        self.config = config if config else getConfig()
        self.logger = getLogger(
            name="Tester", logFile="/var/log/EndToEndTester/Tester.log"
        )
        self.siterm = SiteRMApi(**{"config": self.config, "logger": self.logger})
        setSenseEnv(self.config)
        self.workflowApi = WorkflowCombinedApi()
        self.workflowPhasedApi = WorkflowPhasedApi()
        self.states = {
            "create": "CREATE - READY",
            "modifycreate": "MODIFY - READY",
            "cancel": "CANCEL - READY",
            "cancelrep": "CANCEL - READY",
            "reprovision": "REINSTATE - READY",
            "modify": "MODIFY - READY",
        }
        self.timeouts = copy.deepcopy(self.config["timeouts"])
        self.timings = {}
        self.starttime = 0
        self.workerid = workerid
        self.workerheader = f"Worker {self.workerid}"
        self.response = {
            "create": {},
            "modifycreate": {},
            "cancel": {},
            "cancelrep": {},
            "reprovision": {},
            "modify": {},
        }
        self.httpretry = {
            "retries": self.config.get("httpretries", {}).get("retries", 3),
            "timeout": self.config.get("httpretries", {}).get("timeout", 30),
        }
        self.finalstats = True
        self.vlan = "any"
        self.currentaction = None

    @timer_func
    def _setWorkerHeader(self, header):
        self.workerheader = f"Worker {self.workerid} - {header}"

    @timer_func
    def _reset(self):
        self.logger.info(f"{self.workerid} called reset parameters")
        self.timeouts = copy.deepcopy(self.config["timeouts"])
        self.timings = {}
        self.response = {
            "create": {},
            "modifycreate": {},
            "cancel": {},
            "cancelrep": {},
            "reprovision": {},
            "modify": {},
        }
        self.workerheader = f"Worker {self.workerid}"
        self.finalstats = True
        self.vlan = "any"
        self.currentaction = None

    @timer_func
    def checkifJsonExists(self, pair):
        """Check if json exists"""
        self.logger.info(f"{self.workerid} checking if {pair} exists and locked")
        checkCreateDir(self.config["workdir"])
        fnames = [
            str(pair[0]) + "-" + str(pair[1]),
            str(pair[1]) + "-" + str(pair[0]) + "-" + str(self.vlan),
        ]
        for fname in fnames:
            # If this file present - means data was not recorded yet. Look at DBRecorder process
            filename = os.path.join(self.config["workdir"], fname + ".json")
            if os.path.exists(filename):
                return True
            # If this file present - means there is another process keeps lock (or failed for some unexpected reason)
            filename = os.path.join(self.config["workdir"], fname + ".json.lock")
            if os.path.exists(filename):
                return True
            # If this file present - means DB Recorded results - but identified that there was failure. Keep it
            # for 3 days (and cancel then) or until manual intervention.
            filename = os.path.join(self.config["workdir"], fname + ".json.dbdone")
            if os.path.exists(filename):
                return True
        return False

    @timer_func
    def creatJsonLock(self, pair):
        """Create json lock"""
        self.logger.info(f"{self.workerid} creating lock file for {pair}")
        checkCreateDir(self.config["workdir"])
        fname = str(pair[0]) + "-" + str(pair[1]) + "-" + str(self.vlan)
        filename = os.path.join(self.config["workdir"], fname + ".json.lock")
        with open(filename, "w", encoding="utf-8") as fd:
            json.dump({"worker": self.workerheader, "timestamp": getUTCnow()}, fd)

    @timer_func
    def writeJsonOutput(self, pair):
        """Write json output"""
        # Generate filename (it can either pair (0,1) or (1,0))
        fname = str(pair[0]) + "-" + str(pair[1]) + "-" + str(self.vlan)
        filename = os.path.join(self.config["workdir"], fname + ".json")
        with open(filename, "w", encoding="utf-8") as fd:
            json.dump(self.response, fd)
        # Delete json lock
        filename = os.path.join(self.config["workdir"], fname + ".json.lock")
        if os.path.exists(filename):
            os.remove(filename)

    @timer_func
    def _logTiming(self, status, call, configstatus, timestamp):
        """Log the timing of the function"""
        self.timings.setdefault(call, {})
        if "starttime" not in self.timings[call]:
            self.timings[call]["starttime"] = self.starttime
        if status not in self.timings[call]:
            self.timings[call][status] = {"entertime": timestamp, "configStatus": {}}
        if configstatus not in self.timings[call][status]["configStatus"]:
            self.timings[call][status]["configStatus"][configstatus] = timestamp

    @timer_func
    def _getManifest(self, si_uuid):
        """Get manifest from sense-o"""
        self.logger.info(f"{self.workerid} Get manifest for {si_uuid}")
        template = {
            "Ports": [
                {
                    "Port": "?terminal?",
                    "Name": "?port_name?",
                    "Vlan": "?vlan?",
                    "Mac": "?port_mac?",
                    "IPv6": "?port_ipv6?",
                    "IPv4": "?port_ipv4?",
                    "Node": "?node_name?",
                    "Peer": "?peer?",
                    "Site": "?site?",
                    "Host": [
                        {
                            "Interface": "?host_port_name?",
                            "Name": "?host_name?",
                            "IPv4": "?ipv4?",
                            "IPv6": "?ipv6?",
                            "Mac": "?mac?",
                            "sparql": 'SELECT DISTINCT ?host_port ?ipv4 ?ipv6 ?mac WHERE { ?host_vlan_port nml:isAlias ?vlan_port. ?host_port nml:hasBidirectionalPort ?host_vlan_port. OPTIONAL {?host_vlan_port mrs:hasNetworkAddress  ?ipv4na. ?ipv4na mrs:type "ipv4-address". ?ipv4na mrs:value ?ipv4.} OPTIONAL {?host_vlan_port mrs:hasNetworkAddress  ?ipv6na. ?ipv6na mrs:type "ipv6-address". ?ipv6na mrs:value ?ipv6.} OPTIONAL {?host_vlan_port mrs:hasNetworkAddress  ?macana. ?macana mrs:type "mac-address". ?macana mrs:value ?mac.} FILTER NOT EXISTS {?sw_svc mrs:providesSubnet ?vlan_subnt. ?vlan_subnt nml:hasBidirectionalPort ?host_vlan_port.} }',
                            "sparql-ext": 'SELECT DISTINCT ?host_name ?host_port_name  WHERE {?host a nml:Node. ?host nml:hasBidirectionalPort ?host_port. OPTIONAL {?host nml:name ?host_name.} OPTIONAL {?host_port mrs:hasNetworkAddress ?na_pn. ?na_pn mrs:type "sense-rtmon:name". ?na_pn mrs:value ?host_port_name.} }',
                            "required": "false",
                        }
                    ],
                    "sparql": "SELECT DISTINCT  ?vlan_port  ?vlan  WHERE { ?subnet a mrs:SwitchingSubnet. ?subnet nml:hasBidirectionalPort ?vlan_port. ?vlan_port nml:hasLabel ?vlan_l. ?vlan_l nml:value ?vlan. }",
                    "sparql-ext": 'SELECT DISTINCT ?terminal ?port_name ?node_name ?peer ?site ?port_mac ?port_ipv4 ?port_ipv6 WHERE { { ?node a nml:Node. ?node nml:name ?node_name. ?node nml:hasBidirectionalPort ?terminal. ?terminal nml:hasBidirectionalPort ?vlan_port. OPTIONAL { ?terminal mrs:hasNetworkAddress ?na_pn. ?na_pn mrs:type "sense-rtmon:name". ?na_pn mrs:value ?port_name. } OPTIONAL { ?terminal nml:isAlias ?peer. } OPTIONAL { ?site nml:hasNode ?node. } OPTIONAL { ?site nml:hasTopology ?sub_site. ?sub_site nml:hasNode ?node. } OPTIONAL { ?terminal mrs:hasNetworkAddress ?naportmac. ?naportmac mrs:type "mac-address". ?naportmac mrs:value ?port_mac. } OPTIONAL { ?vlan_port mrs:hasNetworkAddress ?ipv4na. ?ipv4na mrs:type "ipv4-address". ?ipv4na mrs:value ?port_ipv4. } OPTIONAL { ?vlan_port mrs:hasNetworkAddress ?ipv6na. ?ipv6na mrs:type "ipv6-address". ?ipv6na mrs:value ?port_ipv6. } } UNION { ?site a nml:Topology. ?site nml:name ?node_name. ?site nml:hasBidirectionalPort ?terminal. ?terminal nml:hasBidirectionalPort ?vlan_port. OPTIONAL { ?terminal mrs:hasNetworkAddress ?na_pn. ?na_pn mrs:type "sense-rtmon:name". ?na_pn mrs:value ?port_name. } OPTIONAL { ?terminal nml:isAlias ?peer. } OPTIONAL { ?terminal mrs:hasNetworkAddress ?naportmac. ?naportmac mrs:type "mac-address". ?naportmac mrs:value ?port_mac. } OPTIONAL { ?vlan_port mrs:hasNetworkAddress ?ipv4na. ?ipv4na mrs:type "ipv4-address". ?ipv4na mrs:value ?port_ipv4. } OPTIONAL { ?vlan_port mrs:hasNetworkAddress ?ipv6na. ?ipv6na mrs:type "ipv6-address". ?ipv6na mrs:value ?port_ipv6. } } }',
                    "required": "true",
                }
            ]
        }
        self.workflowApi.si_uuid = si_uuid
        response = self.workflowApi.manifest_create(dumpJson(template))
        json_response = loadJson(response)
        if "jsonTemplate" not in json_response:
            self.logger.warning(f"WARNING: {si_uuid} did not receive correct output!")
            self.logger.warning(f"WARNING: Response: {response}")
            return {}
        manifest = loadJson(json_response["jsonTemplate"])
        return manifest

    @timer_func
    def _validateState(self, status, call):
        """Validate the state of the service instance creation"""
        states = []
        self.logger.debug(f"({self.workerheader}) status={status.get('state')}")
        self.logger.debug(
            f"({self.workerheader}) configStatus={status.get('configState')}"
        )
        self._logTiming(
            status.get("state"), call, status.get("configState"), getUTCnow()
        )
        # If state in failed, raise exception
        if status.get("state") == "CREATE - FAILED":
            raise ValueError("Create status in SENSE-O is FAILED.")
        if status.get("state") == "CANCEL - FAILED":
            raise ValueError("Cancel status in SENSE-O is FAILED.")
        if status.get("state") == "REINSTATE - FAILED":
            raise ValueError("Reinstate status in SENSE-O is FAILED.")
        if status.get("state") == self.states[call]:
            states.append(True)
        if status.get("configState") == "STABLE":
            states.append(True)
        else:
            states.append(False)
        if not states:
            return False
        return all(states)

    @timer_func
    def _loopStatusCall(self, serviceuuid, calltype):
        """Loop Status Call and validate if it is final"""
        status = self.workflowApi.instance_get_status(si_uuid=serviceuuid, verbose=True)
        iterationcounter = 0
        sleeptime = 1
        runUntil = getUTCnow() + self.timeouts.get(
            calltype, 1200
        )  # 20 mins by default;
        while not self._validateState(status, calltype):
            sleeptime = (iterationcounter // 15) + 1
            iterationcounter += 1
            time.sleep(sleeptime)
            status = self.workflowApi.instance_get_status(
                si_uuid=serviceuuid, verbose=True
            )
            self.logger.info(
                f"{self.workerid} {calltype} {serviceuuid} Get status timings. Remaining runtime {runUntil - getUTCnow()} Iteration: {iterationcounter}. Sleep time: {sleeptime}"
            )
            if runUntil - getUTCnow() <= 0:
                return {
                    "error": "Timeout while validating instance",
                    "timeout": True,
                    "finalstate": "NOTOK",
                    "state": status["state"],
                    "response": status,
                }
        return status

    @timer_func
    def __getManifest(self, output, uuid):
        """Get manifest with retries"""
        retry = 0
        while retry <= self.httpretry["retries"]:
            try:
                # get Manifest
                output["manifest"] = self._getManifest(si_uuid=uuid)
                retry = self.httpretry["retries"] + 1
            except Exception as ex:
                msg = f"Got Exception {ex} while getting manifest for {uuid}"
                self.logger.error(msg)
                self.logger.debug(getFullTraceback(ex))
                output["manifest"] = {}
                output["manifest-error"] = msg
                self.logger.info(f'Will retry after {self.httpretry["timeout"]}seconds')
                retry += 1
                time.sleep(self.httpretry["timeout"])
        return output

    @timer_func
    def __getValidation(self, output, uuid):
        """Get validation with retries"""
        retry = 0
        while retry <= self.httpretry["retries"]:
            try:
                # get Validation results
                output["validation"] = self.workflowPhasedApi.instance_verify(
                    si_uuid=uuid
                )
                retry = self.httpretry["retries"] + 1
            except Exception as ex:
                msg = f"Got Exception {ex} while getting validation for {uuid}"
                self.logger.error(msg)
                self.logger.debug(getFullTraceback(ex))
                output["validation"] = {}
                output["validation-error"] = msg
                self.logger.info(f'Will retry after {self.httpretry["timeout"]}seconds')
                retry += 1
                time.sleep(self.httpretry["timeout"])
        return output

    @timer_func
    def _setFinalStats(self, output, newreq, uuid):
        """Get final status and all info to output"""
        if newreq:
            output["req"] = newreq
        output['finalstatetimestamp'] = getUTCnow()
        if uuid and not self._checkpathfindissue(output, "guaranteedCapped"):
            if self.currentaction not in ["cancel", "cancelrep", "cancelarch"]:
                output = self.__getManifest(output, uuid)
            output = self.__getValidation(output, uuid)
        return output

    @timer_func
    def _checkpathfindissue(self, retDict, reqtype):
        """Check if there was path finding issue."""
        # This only applies if guaranteedCapped and error has string:
        # cannot find feasible path for connection
        if reqtype == "guaranteedCapped":
            if (
                "error" in retDict
                and "cannot find feasible path for connection" in retDict["error"]
            ):
                self.logger.info(f"{self.workerid} Failed to find path. Return True")
                return True
        return False

    # ==================================================================================================
    # CREATE
    # ==================================================================================================
    @timer_func
    def _deletefailedpath(self):
        """Delete failed path request"""
        if self.workflowApi.si_uuid:
            try:
                self.workflowApi.instance_delete(si_uuid=self.workflowApi.si_uuid)
            except Exception as ex:
                self.logger.error(
                    f"Failed to delete instance which failed path finding. Ex: {ex}"
                )
                self.logger.debug(getFullTraceback(ex))

    @timer_func
    def create(self, pair):
        """Create a service instance in SENSE-0"""
        self.currentaction = "create"
        submittests = {}
        if self.config.get("submissiontemplate", None) == "nettest":
            submittests = net_request
        elif self.config.get("submissiontemplate", None) == "l3_request":
            submittests = l3_request
        else:
            submittests = requests
        for reqtype, template in submittests.items():
            try:
                retDict, newreq, uuid = self.__create(pair, reqtype, template)
                # Check if there is an error and path failure. guaranteedCapped
                if not self._checkpathfindissue(retDict, reqtype):
                    # If there was no create timeout issue - submit and monitor ping
                    finalReturn = self._setFinalStats(retDict, newreq, uuid)
                    if "finalstate" in retDict and retDict["finalstate"] == "OK":
                        if not self.config.get("ignoreping", False):
                            return self.siterm.testPing(finalReturn), retDict.get(
                                "error"
                            )
                        self.logger.info(
                            f"{self.workerheader} Ignoring ping test due to config parameter set"
                        )
                    return finalReturn, retDict.get("error")
                # If we reach here - means guaranteedCapped failed with pathFinding.
                if reqtype == "guaranteedCapped":
                    self.logger.warning(
                        f"{self.workerheader} {reqtype} for path request failed with path find. will retry bestEffort"
                    )
                    self._deletefailedpath()
            except Exception as ex:
                uuid = (
                    None if not self.workflowApi.si_uuid else self.workflowApi.si_uuid
                )
                self.logger.debug(getFullTraceback(ex))
                return (
                    self._setFinalStats(
                        {"error": f"({self.workerheader}) Error: {ex}"}, None, uuid
                    ),
                    ex,
                )
        errmsg = (
            f"({self.workerheader}) reached point it should not reach. Script issue!"
        )
        return {"error": errmsg}, errmsg

    @staticmethod
    def __getpart(part):
        """Get part - if + then return last 2 parts. If fails - return full part"""
        ret = part.split(":")[-1]
        if ret == "+":
            try:
                ret = ":".join(part.split(":")[-3:-1])
            except Exception:
                ret = part
        return ret

    def _getIPRange(self, pairname):
        """Get IP Range for the pair"""
        # Get the IPv6 Range from config
        iprange = self.config.get("entries", {}).get(pairname, {}).get("ipv6_prefix", None)
        if not iprange:
            errmsg = (f"({self.workerheader}) No IPv6 prefix found for {pairname} in config. Cannot create L3 request.")
            self.logger.error(errmsg)
            return None, errmsg
        return iprange, None

    def _getAlias(self, pair):
        """Get alias for the pair"""
        return f"{timestampToDate(getUTCnow())} {self.__getpart(pair[0])}-{self.__getpart(pair[1])}-{self.vlan}"

    @timer_func
    def __create(self, pair, reqtype, template):
        """Create a service instance in SENSE-0"""
        self.starttime = getUTCnow()
        self._logTiming("CREATE", "create", "create", getUTCnow())
        self.workflowApi = WorkflowCombinedApi()
        newreq = copy.deepcopy(template)
        self.response["info"] = {
            "pair": pair,
            "worker": self.workerid,
            "time": getUTCnow(),
            "requesttype": reqtype,
        }
        newreq["data"]["connections"][0]["terminals"][0]["vlan_tag"] = self.vlan
        newreq["data"]["connections"][0]["terminals"][0]["uri"] = pair[0]
        # In case it is L3 request, we need to get the IPv6 Range to use
        if self.config.get("submissiontemplate", None) == "l3_request":
            # Get the IPv6 Range from config
            iprange, errmsg = self._getIPRange(pair[0])
            if errmsg:
                return {"error": errmsg}, newreq, None
            newreq["data"]["connections"][0]["terminals"][0]["ipv6_prefix_list"] = iprange
        # Set the VLAN tag and URI for the second terminal
        newreq["data"]["connections"][0]["terminals"][1]["vlan_tag"] = self.vlan
        newreq["data"]["connections"][0]["terminals"][1]["uri"] = pair[1]
        # In case it is L3 requests, we need to set the IPv6 Range to use
        if self.config.get("submissiontemplate", None) == "l3_request":
            # Get the IPv6 Range from config
            iprange, errmsg = self._getIPRange(pair[1])
            if errmsg:
                return {"error": errmsg}, newreq, None
            newreq["data"]["connections"][0]["terminals"][1]["ipv6_prefix_list"] = iprange
        newreq["alias"] = self._getAlias(pair)
        self.response["info"]["req"] = newreq
        self.workflowApi.si_uuid = None
        newuuid = self.workflowApi.instance_new()
        self.response["info"]["uuid"] = newuuid
        try:
            self.logger.info(f"{self.workerid} Create new instance {newreq}")
            response = self.workflowApi.instance_create(json.dumps(newreq))
            self.logger.info(
                f"({self.workerheader}) creating service instance: {response}"
            )
        except ValueError as ex:
            errmsg = f"Error during create: {ex}"
            self.logger.error(errmsg)
            return {"error": errmsg, "errorlevel": "senseo"}, newreq, newuuid
        except Exception as ex:
            errmsg = f"Exception error during create: {ex}"
            self.logger.error(errmsg)
            self.logger.debug(getFullTraceback(ex))
            return {"error": errmsg}, newreq, newuuid
        try:
            self.logger.info(f"{self.workerid} Call provision.")
            self.workflowApi.instance_operate("provision", async_req=True, sync=False)
        except Exception as ex:
            errmsg = f"Exception during instance operate: {ex}"
            self.logger.error(errmsg)
            self.logger.debug(getFullTraceback(ex))
            return {"error": errmsg, "errorlevel": "senseo"}, newreq, newuuid
        # Loop Status call for create and look for final state
        status = self._loopStatusCall(response["service_uuid"], "create")
        self.logger.info(f"({self.workerheader}) Final submit status: {status}")
        state = self._validateState(status, "create")
        response["state"] = state
        self.logger.info(f"({self.workerheader}) provision complete")
        if bool(status.get("timeout", False)):
            minutes = self.timeouts.get("create", 1200) // 60
            errmsg = f'Create timeout of {minutes} minutes. Please check {response["service_uuid"]}'
            return (
                {"error": errmsg, "state": state, "response": response},
                newreq,
                newuuid,
            )
        return (
            {"finalstate": "OK", "state": state, "response": response},
            newreq,
            newuuid,
        )

    # ==================================================================================================
    # CANCEL
    # ==================================================================================================
    @timer_func
    def _cancelwrap(self, si_uuid, force):
        """Wrap the cancel function"""
        try:
            self.logger.info(
                f"{self.workerid} call cancel for {si_uuid} with force: {force}"
            )
            self.workflowApi.instance_operate("cancel", si_uuid=si_uuid, force=force)
        except ValueError as ex:
            self.logger.error(f"({self.workerheader}) Error: {ex}")
            # Check status and return
            status = self.workflowApi.instance_get_status(si_uuid=si_uuid, verbose=True)
            self.logger.info(f"({self.workerheader}) Final cancel status: {status}")
            self.logger.info(status)

    @timer_func
    def cancel(self, serviceuuid, delete=False, archive=False):
        """Cancel a service instance in SENSE-0"""
        try:
            retDict = self.__cancel(serviceuuid, delete, archive)
            finalout = self._setFinalStats(retDict, None, serviceuuid)
            if retDict.get("finalstate", "NOTOKUNKNOWN") != "NOTOKUNKNOWN":
                if archive and delete:
                    self.logger.debug("Archive and Delete set at same time. Should not happen!")
                elif self._validateState(retDict["response"], self.currentaction):
                    if delete:
                        self.workflowApi.instance_delete(si_uuid=serviceuuid)
                    if archive:
                        self.workflowApi.instance_archive(si_uuid=serviceuuid)
                elif archive:
                    self.workflowApi.instance_archive(si_uuid=serviceuuid)
            return finalout, retDict.get("error")
        except Exception as ex:
            self.logger.debug(getFullTraceback(ex))
            return (
                self._setFinalStats(
                    {"error": f"Exception during Cancel: {ex}", "finalstate": "NOTOK"},
                    None,
                    serviceuuid,
                ),
                ex,
            )

    @timer_func
    def __cancel(self, serviceuuid, delete=False, archive=False):
        """Cancel a service instance in SENSE-0"""
        self.starttime = getUTCnow()
        self._logTiming("CREATE", self.currentaction, "create", getUTCnow())
        self.logger.info(f"{self.workerid} Get instance status for {serviceuuid}")
        status = self.workflowApi.instance_get_status(si_uuid=serviceuuid)
        if "error" in status:
            return {"error": status["error"], "finalstate": "NOTOK", "response": status}
        if (
            "CREATE" not in status
            and "REINSTATE" not in status
            and "MODIFY" not in status
        ):
            return {
                "error": f"Cannot cancel an instance in '{status}' status...",
                "finalstate": "NOTOK",
            }

        self._cancelwrap(serviceuuid, bool("READY" not in status))
        # Loop Status call for cancel and look for final state
        status = self._loopStatusCall(serviceuuid, self.currentaction)
        if bool(status.get("timeout", False)):
            minutes = self.timeouts.get("cancel", 1200) // 60
            return {"finalstate": "NOTOK",
                    "response": f"Timeout of {minutes} minutes was reached while cancelling instance and instance did not reach final state"}
        self.logger.info(f"({self.workerheader}) Final cancel status: {status}")
        if archive and delete:
            self.logger.debug("Archive and Delete set at same time. Should not happen!")
        elif self._validateState(status, self.currentaction):
            if delete:
                return {"finalstate": "OK", "response": status}
            if archive:
                return {"finalstate": "OKARCHIVE", "response": status}
            return {"finalstate": "OK", "response": status}
        elif archive:
            return {"finalstate": "NOTOKARCHIVE", "response": status}
        self.logger.info(f"({self.workerheader}) cancel complete")
        return {"finalstate": "NOTOKDELETE", "response": status}

    # ==================================================================================================
    # REPROVISION
    # ==================================================================================================
    @timer_func
    def reprovision(self, serviceuuid):
        """Reprovision a service instance in SENSE-0"""
        self.currentaction = "reprovision"
        self.starttime = getUTCnow()
        self._logTiming("CREATE", "reprovision", "create", getUTCnow())
        status = self.workflowApi.instance_get_status(si_uuid=serviceuuid)
        if "error" in status:
            raise ValueError(status)
        if "CANCEL" not in status:
            raise ValueError(
                f"({self.workerid}) cannot reprovision an instance in '{status}' status..."
            )
        self.workflowApi.instance_operate(
            "reprovision", si_uuid=serviceuuid, sync="true"
        )
        # Loop Status call for cancel and look for final state
        status = self._loopStatusCall(serviceuuid, "reprovision")
        if bool(status.get("timeout", False)):
            minutes = self.timeouts.get("reprovision", 1200) // 60
            return status, f"Timeout of {minutes} minutes was reached while reprovisioning instance and instance did not reach final state"
        if self._validateState(status, "reprovision"):
            status["finalstate"] = "OK"
            finalReturn = self._setFinalStats(status, None, serviceuuid)
            if not self.config.get("ignoreping", False):
                return self.siterm.testPing(finalReturn), status.get("error")
            self.logger.info(
                f"{self.workerheader} Ignoring ping test due to config parameter set"
            )
            return finalReturn, status.get("error")
        status["finalstate"] = "NOTOK"
        return (
            self._setFinalStats(status, None, serviceuuid),
            "Something has failed in reprovisioning. Check SENSE-O logs for more details",
        )

    # ==================================================================================================
    # MODIFY
    # ==================================================================================================
    @timer_func
    def modify(self, serviceuuid, action="division"):
        """Modify a service instance in SENSE-0"""
        self.starttime = getUTCnow()
        self._logTiming("CREATE", self.currentaction, "create", getUTCnow())
        status = self.workflowApi.instance_get_status(si_uuid=serviceuuid)
        if "error" in status:
            raise ValueError(status)
        if (
            "CREATE" not in status
            and "REINSTATE" not in status
            and "MODIFY" not in status
        ):
            raise ValueError(
                f"({self.workerid}) cannot modify an instance in '{status}' status..."
            )
        # Once we reach here, we need the following information:
        # Need to get original intenet, and modify bandwidth inside of it.
        # and then submit whole additional request again
        originReq = copy.deepcopy(self.response["info"]["req"])
        if (
            originReq["data"]["connections"][0]["bandwidth"]["qos_class"]
            != "guaranteedCapped"
        ):
            # If not guaranteedCapped - we need to modify it to guaranteedCapped
            msg = f"({self.workerheader}) Modify request not possible, as initial submission was not guaranteedCapped. Will modify request"
            self.logger.info(msg)
            return (
                self._setFinalStats(
                    {"finalstate": "OK", "response": None, "infomsg": msg},
                    None,
                    serviceuuid,
                ),
                None,
            )
        # Given we are here - we need to modify the request based on the request type
        if action == "division":
            originReq["data"]["connections"][0]["bandwidth"]["capacity"] = str(
                int(originReq["data"]["connections"][0]["bandwidth"]["capacity"]) // 2
            )
        elif action == "multiply":
            originReq["data"]["connections"][0]["bandwidth"]["capacity"] = str(
                int(originReq["data"]["connections"][0]["bandwidth"]["capacity"]) * 2
            )
        try:
            self.logger.info(f"{self.workerid} Modify instance {originReq}")
            response = self.workflowApi.instance_modify(
                json.dumps(originReq), si_uuid=serviceuuid
            )
            self.logger.info(
                f"({self.workerheader}) modify service instance: {response}"
            )
        except ValueError as ex:
            errmsg = f"Error during modify: {ex}"
            self.logger.error(errmsg)
            return (
                self._setFinalStats(
                    {"finalstate": "NOTOK", "error": errmsg, "errorlevel": "senseo"},
                    originReq,
                    serviceuuid,
                ),
                errmsg,
            )
        except Exception as ex:
            errmsg = f"Exception error during modify: {ex}"
            self.logger.error(errmsg)
            self.logger.debug(getFullTraceback(ex))
            return (
                self._setFinalStats(
                    {"finalstate": "NOTOK", "error": errmsg}, originReq, serviceuuid
                ),
                errmsg,
            )
        # Loop Status call for modify and look for final state
        status = self._loopStatusCall(serviceuuid, self.currentaction)
        if bool(status.get("timeout", False)):
            minutes = self.timeouts.get("modify", 1200) // 60
            return status, f"Timeout of {minutes} minutes was reached while modifying instance and instance did not reach final state"
        if self._validateState(status, self.currentaction):
            status["finalstate"] = "OK"
            finalReturn = self._setFinalStats(status, None, serviceuuid)
            if not self.config.get("ignoreping", False):
                return self.siterm.testPing(finalReturn), status.get("error")
            self.logger.info(
                f"{self.workerheader} Ignoring ping test due to config parameter set"
            )
            return finalReturn, status.get("error")
        status["finalstate"] = "NOTOK"
        return (
            self._setFinalStats(
                {"finalstate": "NOTOK", "response": status}, originReq, serviceuuid
            ),
            "Something has failed in modify. Check SENSE-O logs for more details",
        )

    # ==================================================================================================
    # MAIN RUN
    # ==================================================================================================

    @timer_func
    def run(self, pair):
        """Start loop work"""
        # pylint: disable=too-many-statements
        modaction = "division"
        self._setWorkerHeader(f"{pair[0]}-{pair[1]}-{self.vlan}")
        if self.checkifJsonExists(pair):
            self.logger.info(
                f"({self.workerheader}) Skipping: {pair} - Json file already exists"
            )
            return
        self.creatJsonLock(pair)
        cancelled = False
        try:
            # Create;
            self.currentaction = "create"
            self.response["create"], errmsg = self.create(pair)
            self.logger.info(f"({self.workerheader}) response: {self.response}")
            serviceuuid = (
                self.response.get("create", {}).get("response", {}).get("service_uuid")
            )
            if errmsg:
                raise ValueError(errmsg)
            # Modify after create;
            if self.config.get("modifycreate", True):
                self.currentaction = "modifycreate"
                self.response["modifycreate"], errmsg = self.modify(
                    serviceuuid, modaction
                )
                modaction = "multiply"
                if errmsg:
                    raise ValueError(errmsg)
            else:
                del self.response["modifycreate"]
            if self.config.get("reprovision", False):
                # Cancel;
                self.currentaction = "cancelrep"
                self.response["cancelrep"], errmsg = self.cancel(
                    serviceuuid, False, False
                )
                if errmsg:
                    raise ValueError(errmsg)
                # Reprovision;
                self.currentaction = "reprovision"
                self.response["reprovision"], errmsg = self.reprovision(serviceuuid)
                if errmsg:
                    raise ValueError(errmsg)
            else:
                del self.response["cancelrep"]
                del self.response["reprovision"]
            if self.config.get("modify", False):
                # Modify;
                self.currentaction = "modify"
                self.response["modify"], errmsg = self.modify(serviceuuid, modaction)
                if errmsg:
                    raise ValueError(errmsg)
            else:
                del self.response["modify"]
            # Cancel;
            self.currentaction = "cancel"
            self.response["cancel"], errmsg = self.cancel(serviceuuid, True, False)
            if errmsg:
                raise ValueError(errmsg)
            cancelled = True
        except ValueError as ex:
            self.logger.error(f"({self.workerheader}) Error: {ex}")
            self.logger.error(
                "This will not cancel it if not cancelled. Will keep instance as is"
            )
            cancelled = True
        except Exception as ex:
            self.logger.error(
                f"({self.workerheader}) Error: {sys.exc_info()}. Exception: {ex}"
            )
            self.logger.debug(getFullTraceback(ex))
        if self.response and not cancelled:
            try:
                if self.config.get("archiveifFailure", True):
                    self.logger.info(
                        "Archive if Failed Flag is True. Got error. Will issue cancel and archive."
                    )
                    self.currentaction = "cancelarch"
                    self.response["cancelarch"], errmsg = self.cancel(
                        serviceuuid, False, True
                    )
                else:
                    self.logger.info(
                        "Archive flag is False and we got Error. Leave instance not canceled/archived"
                    )
            except Exception as exc:
                self.logger.error(f"({self.workerheader}) Error: {exc}")
                self.logger.debug(getFullTraceback(exc))
        self.logger.info(f"({self.workerheader}) Final response:")
        self.response["timings"] = self.timings
        self.logger.info(pprint.pformat(self.response))
        # Write response into output file
        self.writeJsonOutput(pair)

    @timer_func
    def startwork(self):
        """Process tasks from the queue"""
        while not self.task_queue.empty():
            try:
                if pauseTesting(
                    os.path.join(self.config["workdir"], "pause-endtoend-testing")
                ):
                    self.logger.info(
                        "Pause testing flag set. Will not get new work from the queue"
                    )
                    time.sleep(30)
                else:
                    pair = self.task_queue.get_nowait()
                    self.logger.info(f"Worker {self.workerid} processing pair: {pair}")
                    # In case we have vlans, we need also to use vlan tag. Otherwise, we use default
                    self.vlan = "any"
                    vlanrange = getvlanrange(self.config)
                    self.logger.info(f"Worker {self.workerid} vlan range: {vlanrange}")
                    successvlans = []
                    # Loop via all vlans.
                    for vlan in vlanrange:
                        while pauseTesting(
                            os.path.join(
                                self.config["workdir"], "pause-endtoend-testing"
                            )
                        ):
                            self.logger.info(
                                "Pause testing flag set. Will not get new to execute new vlan test"
                            )
                            time.sleep(30)
                        if vlan in successvlans:
                            self.logger.info(
                                f"Worker {self.workerid} already processed with vlan: {vlan}"
                            )
                            continue
                        self._reset()
                        self.vlan = vlan
                        self.logger.info(
                            f"Worker {self.workerid} processing pair: {pair} with vlan: {vlan}"
                        )
                        self.run(pair)
                        if (
                            self.response.get("create", {}).get("finalstate", None)
                            == "OK"
                            and self.vlan != "any"
                        ):
                            self.logger.info(
                                f"Worker {self.workerid} processing pair: {pair} with vlan: {vlan} - success"
                            )
                            successvlans.append(vlan)
                    self.task_queue.task_done()
            except queue.Empty:
                break


def filterIncludes(config, item):
    """Filter includes/excludes"""
    if "filter" in config:
        if "exclude" in config["filter"]:
            if item in config["filter"]["exclude"]:
                return False
            return True
        if "include" in config["filter"]:
            if item in config["filter"]["include"]:
                return True
            return False
    return True


def getPortsFromSense(config, mlogger):
    """Call SENSE and get all ports"""
    workflowApi = WorkflowCombinedApi()
    client = DiscoverApi()
    alldomains = client.discover_get()
    allEntries = []
    for domdict in alldomains.get("domains", []):
        if domdict.get("domain_uri") != config["entriesdynamic"]:
            continue
        sparql = "SELECT ?port   WHERE { &lt;REPLACEME&gt; nml:hasBidirectionalPort ?port.  }"
        sparql = sparql.replace("REPLACEME", config["entriesdynamic"])
        query = {
            "All Endpoint Ports": [
                {"URI": "?port?", "sparql-ext": sparql, "required": "true"}
            ]
        }
        try:
            allhosts = workflowApi.manifest_create(json.dumps(query))
            allhosts["jsonTemplate"] = json.loads(allhosts.get("jsonTemplate"))
            for host in allhosts.get("jsonTemplate", {}).get("All Endpoint Ports", []):
                if host["URI"] not in allEntries:
                    if filterIncludes(config, host["URI"]):
                        allEntries.append(host["URI"])
        except Exception as ex:
            mlogger.debug(f"Received an exception: {ex}")
            mlogger.debug(getFullTraceback(ex))
    mlogger.info(f"Here is full list of entries received: {allEntries}")
    return allEntries


def getAllGroupedHosts(config, mlogger):
    """Get all grouped hosts"""
    allEntries = []
    # First we use entries config
    for key, val in config.get("entries", {}).items():
        if val.get("disabled", False):
            mlogger.info(
                f"Entry {key} is disabled. Will not include in test. Config params for entry: {val}"
            )
            continue
        # if this is l3 request, check that ipv6_range is set
        if config.get("submissiontemplate", None) == "l3_request":
            if not val.get("ipv6_prefix", None):
                mlogger.error(
                    f"Entry {key} is L3 request, but ipv6_prefix is not set. Will not include in test."
                )
                continue
        allEntries.append(key)
    # Second - if not available - we check if dynamic parameter set for a specific domain
    # entriesdynamic: <domainname>
    if not allEntries and config.get("entriesdynamic", None):
        mlogger.info(
            f'No entries found in config. Will use dynamic entries from domain: {config["entriesdynamic"]}'
        )
        allEntries = getPortsFromSense(config, mlogger)
    # Generate a list of combinations
    # if vlans defined, we need to do combinations between vlansto
    if config.get("vlans", None):
        uniquePairs = []
        for urn in config.get("vlansto", []):
            for urn1 in allEntries:
                if urn == urn1:
                    continue
                combo = (urn, urn1)
                if combo not in uniquePairs:
                    uniquePairs.append(combo)
                    continue
                combo = (urn1, urn)
                if combo not in uniquePairs:
                    uniquePairs.append(combo)
                    continue
        mlogger.info(f"Here is new list of unique pairs to test: {uniquePairs}")
        return uniquePairs
    uniquePairs = list(combinations(allEntries, 2))
    mlogger.info(f"Here is new list of unique pairs to test: {uniquePairs}")
    return uniquePairs


def checkconfig(config):
    """Check config"""
    if config.get("entries", None) and config.get("entriesdynamic", None):
        raise ValueError(
            "Both entries and entriesdynamic are set. Please use only one of them."
        )
    if config.get("entries", None) and config.get("entriessitename", None):
        raise ValueError(
            "Both entries and entriessitename are set. Please use only one of them."
        )
    if not config.get("entries", None) and not config.get("entriesdynamic", None):
        raise ValueError(
            "Neither entries nor entriesdynamic are set. Please use one of them."
        )
    if not config.get("entries", None) and (
        not config.get("entriesdynamic", None)
        or not config.get("entriessitename", None)
    ):
        raise ValueError(
            "entriesdynamic or entriessitename is not set. Please set both of them."
        )
    if not config.get("totalThreads", None):
        raise ValueError("totalThreads is not set. Please set it.")
    if not config.get("workdir", None):
        raise ValueError("workdir is not set. Please set it.")
    if not config.get("runInterval", None):
        raise ValueError("runInterval is not set. Please set it.")
    # if vlans defined, that works only with entries;
    if config.get("vlans", None) and not config.get("entries", None):
        raise ValueError("VLANs are defined, but entries are not. Please set entries.")
    if config.get("vlans", None) and not config.get("vlansto", None):
        raise ValueError("VLANs are defined, but vlansto is not. Please set vlansto.")


def main(config, starttime, nextRunTime):
    """Main Run"""
    mlogger = getLogger(name="Tester", logFile="/var/log/EndToEndTester/Tester.log")
    while pauseTesting(os.path.join(config["workdir"], "pause-endtoend-testing")):
        mlogger.info("Seems Flag to Pause testing is set. Will postpone for 30s")
        statusout = {
            "alive": False,
            "totalworkers": config["totalThreads"],
            "totalqueue": 0,
            "remainingqueue": 0,
            "updatedate": getUTCnow(),
            "insertdate": getUTCnow(),
            "starttime": starttime,
            "nextrun": nextRunTime,
        }
        dumpFileJson(os.path.join(config["workdir"], "testerinfo" + ".run"), statusout)
        time.sleep(30)
    mlogger.info("=" * 80)
    checkconfig(config)
    mlogger.info("Get all group host pairs")
    unique_pairs = getAllGroupedHosts(config, mlogger)
    threads = []
    workers = []
    # Shuffle randomly
    random.shuffle(unique_pairs)
    # Limit the number of pairs to test based on configuration
    if len(unique_pairs) > config.get("maxpairs", 100):
        unique_pairs = unique_pairs[: config.get("maxpairs", 100)]
        mlogger.info(f"List of unique pairs is more than {config.get('maxpairs', 100)}")
        mlogger.info(f"Here is new list: {unique_pairs}")
    # Create a queue and populate it with tasks
    task_queue = queue.Queue()
    for pair in unique_pairs:
        task_queue.put(pair)

    mlogger.info("=" * 80)
    if config["totalThreads"] == 1 and config.get("nothreading", False):
        mlogger.info("Starting one threads")
        worker = SENSEWorker(task_queue, 0, config)
        worker.startwork()
        return

    mlogger.info(f"Starting {config['totalThreads']} threads (Multithreading)")
    for i in range(config["totalThreads"]):
        worker = SENSEWorker(task_queue, i, config)
        workers.append(worker)
        thworker = threading.Thread(target=worker.startwork, args=())
        threads.append((thworker, worker))
        thworker.start()
    mlogger.info("join all threads and wait for finish")
    statusout = {
        "alive": True,
        "totalworkers": config["totalThreads"],
        "totalqueue": len(unique_pairs),
        "remainingqueue": task_queue.qsize(),
        "updatedate": getUTCnow(),
        "insertdate": getUTCnow(),
        "starttime": starttime,
        "nextrun": nextRunTime,
    }
    while any(t[0].is_alive() for t in threads):
        alive = [t[0].is_alive() for t in threads]
        statusout["alive"] = any(alive)
        statusout["remainingqueue"] = task_queue.qsize()
        mlogger.info(f"Remaining queue size: {task_queue.qsize()}")
        # Write status out file
        dumpFileJson(os.path.join(config["workdir"], "testerinfo" + ".run"), statusout)
        time.sleep(30)
        if pauseTesting(os.path.join(config["workdir"], "pause-endtoend-testing")):
            mlogger.info("Pause testing flag set. Queue might not be decreasing!")

    for thworker, _ in threads:
        thworker.join()

    # Write status file again - everything has finished;
    statusout = {
        "alive": False,
        "totalworkers": 0,
        "totalqueue": 0,
        "remainingqueue": 0,
        "updatedate": getUTCnow(),
        "insertdate": getUTCnow(),
        "starttime": starttime,
        "nextrun": nextRunTime,
    }
    dumpFileJson(os.path.join(config["workdir"], "testerinfo" + ".run"), statusout)
    mlogger.info("all threads finished")


if __name__ == "__main__":
    logger = getLogger(
        name="Tester", logFile="/var/log/EndToEndTester/Tester.log", logtoStdout=True
    )
    yamlconfig = getConfig()
    startimer = getUTCnow()
    nextRun = 0
    while True:
        if nextRun <= getUTCnow():
            logger.info("Timer passed. Running main")
            if yamlconfig.get("configlocation", None):
                yamlconfig = loadYaml(fetchRemoteConfig(yamlconfig["configlocation"]))
            nextRun = getUTCnow() + yamlconfig["runInterval"]
            main(yamlconfig, startimer, nextRun)
        else:
            logger.info(
                f"Sleeping for {yamlconfig['sleepbetweenruns']} seconds. Timer not passed"
            )
            logger.info(
                f"Next run: {nextRun}. Current time: {getUTCnow()}. Difference: {nextRun - getUTCnow()}"
            )
            time.sleep(yamlconfig["sleepbetweenruns"])
