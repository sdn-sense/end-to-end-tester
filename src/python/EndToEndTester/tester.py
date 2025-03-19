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
import json
import time
import copy
import pprint
import threading
import queue
from itertools import combinations
from EndToEndTester.utilities import loadJson, dumpJson, getUTCnow, getConfig, checkCreateDir, getLogger, setSenseEnv, dumpFileJson
from sense.common import classwrapper
from sense.client.workflow_combined_api import WorkflowCombinedApi
from sense.client.workflow_phased_api import WorkflowPhasedApi


requests = {'guaranteedCapped': {
  "service": "dnc",
  "alias": "REPLACEME",
  "data": {
    "type": "Multi-Path P2P VLAN",
    "connections": [
      {"bandwidth": {"qos_class": "guaranteedCapped",
                      "capacity": "1000"},
       "name": "Connection 1",
       "ip_address_pool": {"netmask": "/64",
                            "name": "AutoGOLE-Test-IPv6-Pool"},
       "terminals": [
          {"vlan_tag": "any",
            "assign_ip": True,
            "uri": "REPLACEME"},
          {"vlan_tag": "any",
           "assign_ip": True,
           "uri": "REPLACEME"}],
       "assign_debug_ip": True}]}},
           'bestEffort': {
  "service": "dnc",
  "alias": "REPLACEME",
  "data": {
    "type": "Multi-Path P2P VLAN",
    "connections": [
      {"bandwidth": {"qos_class": "bestEffort"},
       "name": "Connection 1",
       "ip_address_pool": {"netmask": "/64",
                            "name": "AutoGOLE-Test-IPv6-Pool"},
       "terminals": [
          {"vlan_tag": "any",
            "assign_ip": True,
            "uri": "REPLACEME"},
          {"vlan_tag": "any",
           "assign_ip": True,
           "uri": "REPLACEME"}],
       "assign_debug_ip": True}]}}
}

def timer_func(func):
    """Decorator function to calculate the execution time of a function"""
    def wrap_func(*args, **kwargs):
        t1 = getUTCnow()
        result = func(*args, **kwargs)
        t2 = getUTCnow()
        print(f'== Function {func.__name__!r} executed in {(t2 - t1):.4f}s')
        print(f'== Function {func.__name__!r} returned: {result}')
        print(f'== Function {func.__name__!r} args: {args}')
        print(f'== Function {func.__name__!r} kwargs: {kwargs}')
        return result
    return wrap_func

@classwrapper
class SENSEWorker():
    """SENSE Worker class"""

    def __init__(self, task_queue, workerid=0, config=None):
        self.task_queue = task_queue
        self.config = config if config else getConfig()
        self.logger = getLogger(name='Tester', logFile='/var/log/EndToEndTester/Tester.log')
        setSenseEnv(self.config)
        self.workflowApi = WorkflowCombinedApi()
        self.workflowPhasedApi = WorkflowPhasedApi()
        self.states = {'create': 'CREATE - READY',
                       'cancel': 'CANCEL - READY'}
                       #'reprovision': 'REINSTATE - READY'}
        self.timeouts = copy.deepcopy(self.config['timeouts'])
        self.timings = {}
        self.starttime = 0
        self.workerid = workerid
        self.workerheader = f'Worker {self.workerid}'
        self.response = {'create': {}, 'cancel': {}}
        self.httpretry = {'retries': 3, 'timeout': 30} # todo - pass via config
        self.finalstats = True

    def _setWorkerHeader(self, header):
        self.workerheader = f"Worker {self.workerid} - {header}"

    def _reset(self):
        self.timeouts = copy.deepcopy(self.config['timeouts'])
        self.timings = {}
        self.response = {'create': {}, 'cancel': {}}
        self.workerheader = f'Worker {self.workerid}'
        self.finalstats = True


    def checkifJsonExists(self, pair):
        """Check if json exists"""
        checkCreateDir(self.config['workdir'])
        fnames = [str(pair[0]) + '-' + str(pair[1]), str(pair[1]) + '-' + str(pair[0])]
        for fname in fnames:
            filename = os.path.join(self.config['workdir'], fname + '.json')
            if os.path.exists(filename):
                return True
            filename = os.path.join(self.config['workdir'], fname + '.json.lock')
            if os.path.exists(filename):
                return True
        return False

    def creatJsonLock(self, pair):
        """Create json lock"""
        checkCreateDir(self.config['workdir'])
        fname = str(pair[0]) + '-' + str(pair[1])
        filename = os.path.join(self.config['workdir'], fname + '.json.lock')
        with open(filename, 'w', encoding='utf-8') as fd:
            json.dump({'worker': self.workerheader, 'timestamp': getUTCnow()}, fd)

    def writeJsonOutput(self, pair):
        """Write json output"""
        # Generate filename (it can either pair (0,1) or (1,0))
        fname = str(pair[0]) + '-' + str(pair[1])
        filename = os.path.join(self.config['workdir'], fname + '.json')
        with open(filename, 'w', encoding='utf-8') as fd:
            json.dump(self.response, fd)
        # Delete json lock
        filename = os.path.join(self.config['workdir'], fname + '.json.lock')
        if os.path.exists(filename):
            os.remove(filename)

    def _logTiming(self, status, call, configstatus, timestamp):
        """Log the timing of the function"""
        self.timings.setdefault(call, {})
        if 'starttime' not in self.timings[call]:
            self.timings[call]['starttime'] = self.starttime
        if status not in self.timings[call]:
            self.timings[call][status] = {'entertime': timestamp, 'configStatus': {}}
        if configstatus not in self.timings[call][status]['configStatus']:
            self.timings[call][status]['configStatus'][configstatus] = timestamp

    def _getManifest(self, si_uuid):
        """Get manifest from sense-o"""
        template = {"Ports": [{
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
                  "sparql": "SELECT DISTINCT ?host_port ?ipv4 ?ipv6 ?mac WHERE { ?host_vlan_port nml:isAlias ?vlan_port. ?host_port nml:hasBidirectionalPort ?host_vlan_port. OPTIONAL {?host_vlan_port mrs:hasNetworkAddress  ?ipv4na. ?ipv4na mrs:type \"ipv4-address\". ?ipv4na mrs:value ?ipv4.} OPTIONAL {?host_vlan_port mrs:hasNetworkAddress  ?ipv6na. ?ipv6na mrs:type \"ipv6-address\". ?ipv6na mrs:value ?ipv6.} OPTIONAL {?host_vlan_port mrs:hasNetworkAddress  ?macana. ?macana mrs:type \"mac-address\". ?macana mrs:value ?mac.} FILTER NOT EXISTS {?sw_svc mrs:providesSubnet ?vlan_subnt. ?vlan_subnt nml:hasBidirectionalPort ?host_vlan_port.} }",
                  "sparql-ext": "SELECT DISTINCT ?host_name ?host_port_name  WHERE {?host a nml:Node. ?host nml:hasBidirectionalPort ?host_port. OPTIONAL {?host nml:name ?host_name.} OPTIONAL {?host_port mrs:hasNetworkAddress ?na_pn. ?na_pn mrs:type \"sense-rtmon:name\". ?na_pn mrs:value ?host_port_name.} }",
                  "required": "false"
                }
              ],
              "sparql": "SELECT DISTINCT  ?vlan_port  ?vlan  WHERE { ?subnet a mrs:SwitchingSubnet. ?subnet nml:hasBidirectionalPort ?vlan_port. ?vlan_port nml:hasLabel ?vlan_l. ?vlan_l nml:value ?vlan. }",
              "sparql-ext": "SELECT DISTINCT ?terminal ?port_name ?node_name ?peer ?site ?port_mac ?port_ipv4 ?port_ipv6 WHERE { { ?node a nml:Node. ?node nml:name ?node_name. ?node nml:hasBidirectionalPort ?terminal. ?terminal nml:hasBidirectionalPort ?vlan_port. OPTIONAL { ?terminal mrs:hasNetworkAddress ?na_pn. ?na_pn mrs:type \"sense-rtmon:name\". ?na_pn mrs:value ?port_name. } OPTIONAL { ?terminal nml:isAlias ?peer. } OPTIONAL { ?site nml:hasNode ?node. } OPTIONAL { ?site nml:hasTopology ?sub_site. ?sub_site nml:hasNode ?node. } OPTIONAL { ?terminal mrs:hasNetworkAddress ?naportmac. ?naportmac mrs:type \"mac-address\". ?naportmac mrs:value ?port_mac. } OPTIONAL { ?vlan_port mrs:hasNetworkAddress ?ipv4na. ?ipv4na mrs:type \"ipv4-address\". ?ipv4na mrs:value ?port_ipv4. } OPTIONAL { ?vlan_port mrs:hasNetworkAddress ?ipv6na. ?ipv6na mrs:type \"ipv6-address\". ?ipv6na mrs:value ?port_ipv6. } } UNION { ?site a nml:Topology. ?site nml:name ?node_name. ?site nml:hasBidirectionalPort ?terminal. ?terminal nml:hasBidirectionalPort ?vlan_port. OPTIONAL { ?terminal mrs:hasNetworkAddress ?na_pn. ?na_pn mrs:type \"sense-rtmon:name\". ?na_pn mrs:value ?port_name. } OPTIONAL { ?terminal nml:isAlias ?peer. } OPTIONAL { ?terminal mrs:hasNetworkAddress ?naportmac. ?naportmac mrs:type \"mac-address\". ?naportmac mrs:value ?port_mac. } OPTIONAL { ?vlan_port mrs:hasNetworkAddress ?ipv4na. ?ipv4na mrs:type \"ipv4-address\". ?ipv4na mrs:value ?port_ipv4. } OPTIONAL { ?vlan_port mrs:hasNetworkAddress ?ipv6na. ?ipv6na mrs:type \"ipv6-address\". ?ipv6na mrs:value ?port_ipv6. } } }",
              "required": "true"
            }
          ]
        }
        self.workflowApi.si_uuid = si_uuid
        response = self.workflowApi.manifest_create(dumpJson(template))
        json_response = loadJson(response)
        if 'jsonTemplate' not in json_response:
            self.logger.warning(f"WARNING: {si_uuid} did not receive correct output!")
            self.logger.warning(f"WARNING: Response: {response}")
            return {}
        manifest = loadJson(json_response['jsonTemplate'])
        return manifest

    def _validateState(self, status, call):
        """Validate the state of the service instance creation"""
        states = []
        self.logger.debug(f"({self.workerheader}) status={status.get('state')}")
        self.logger.debug(f"({self.workerheader}) configStatus={status.get('configState')}")
        self._logTiming(status.get('state'), call, status.get('configState'), getUTCnow())
        # If state in failed, raise exception
        if status.get('state') == 'CREATE - FAILED':
            raise ValueError('Create status in SENSE-O is FAILED.')
        if status.get('state') == self.states[call]:
            states.append(True)
        if status.get('configState') == 'STABLE':
            states.append(True)
        else:
            states.append(False)
        if not states:
            return False
        return all(states)

    def _setFinalStats(self, output, newreq, uuid):
        """Get final status and all info to output"""
        if newreq:
            output['req'] = newreq
        if uuid and not self._checkpathfindissue(output, 'guaranteedCapped'):
            retry = 0
            while retry <= self.httpretry['retries']:
                try:
                    # get Manifest
                    output['manifest'] = self._getManifest(si_uuid=uuid)
                    retry = self.httpretry['retries'] + 1
                except Exception as ex:
                    msg = f'Got Exception {ex} while getting manifest for {uuid}'
                    self.logger.error(msg)
                    output['manifest'] = {}
                    output['manifest-error'] = msg
                    self.logger.info(f'Will retry after {self.httpretry["timeout"]}seconds')
                    retry +=1
                    time.sleep(self.httpretry['timeout'])
            retry = 0
            while retry <= self.httpretry['retries']:
                try:
                    # get Validation results
                    output['validation'] = self.workflowPhasedApi.instance_verify(si_uuid=uuid)
                    retry = self.httpretry['retries'] + 1
                except Exception as ex:
                    msg = f'Got Exception {ex} while getting validation for {uuid}'
                    self.logger.error(msg)
                    output['validation'] = {}
                    output['validation-error'] = msg
                    self.logger.info(f'Will retry after {self.httpretry["timeout"]}seconds')
                    retry +=1
                    time.sleep(self.httpretry['timeout'])
        return output


    def _checkpathfindissue(self, retDict, reqtype):
        """Check if there was path finding issue."""
        # This only applies if guaranteedCapped and error has string:
        # cannot find feasible path for connection
        if reqtype == 'guaranteedCapped':
            if 'error' in retDict and "cannot find feasible path for connection" in retDict['error']:
                return True
        return False

    def _deletefailedpath(self):
        """Delete failed path request"""
        if self.workflowApi.si_uuid:
            try:
                self.workflowApi.instance_delete(si_uuid=self.workflowApi.si_uuid)
            except Exception as ex:
                self.logger.error(f'Failed to delete instance which failed path finding. Ex: {ex}')

    @timer_func
    def create(self, pair):
        """Create a service instance in SENSE-0"""
        for reqtype, template in requests.items():
            try:
                retDict, newreq, uuid = self.__create(pair, reqtype, template)
                # Check if there is an error and path failure. guaranteedCapped
                if not self._checkpathfindissue(retDict, reqtype):
                    return self._setFinalStats(retDict, newreq, uuid), retDict.get('error')
                # If we reach here - means guaranteedCapped failed with pathFinding.
                if reqtype == 'guaranteedCapped':
                    self.logger.warning(f'{self.workerheader} {reqtype} for path request failed with path find. will retry bestEffort')
                    self._deletefailedpath()
            except Exception as ex:
                uuid = None if not self.workflowApi.si_uuid else self.workflowApi.si_uuid
                return self._setFinalStats({'error': f"({self.workerheader}) Error: {ex}"}, None, uuid), ex
        errmsg = f"({self.workerheader}) reached point it should not reach. Script issue!"
        return {'error': errmsg}, None, errmsg

    @timer_func
    def __create(self, pair, reqtype, template):
        """Create a service instance in SENSE-0"""
        self.starttime = getUTCnow()
        self._logTiming('CREATE', 'create', 'create', getUTCnow())
        self.workflowApi = WorkflowCombinedApi()
        newreq = copy.deepcopy(template)
        self.response['info'] = {'pair': pair, 'worker': self.workerid, 'time': getUTCnow(), 'requesttype': reqtype}
        newreq['data']['connections'][0]['terminals'][0]['uri'] = pair[0]
        newreq['data']['connections'][0]['terminals'][1]['uri'] = pair[1]
        newreq['alias'] = f'AUTO-{self.workerid} {pair[0].split(":")[-1]}-{pair[1].split(":")[-1]}'
        self.response['info']['req'] = newreq
        self.workflowApi.si_uuid = None
        newuuid = self.workflowApi.instance_new()
        self.response['info']['uuid'] = newuuid
        try:
            response = self.workflowApi.instance_create(json.dumps(newreq))
            self.logger.info(f"({self.workerheader}) creating service instance: {response}")
        except ValueError as ex:
            errmsg = f"Error during create: {ex}"
            return {'error': errmsg, 'errorlevel': 'senseo'}, newreq, newuuid
        except Exception as ex:
            errmsg = f"Exception error during create: {ex}"
            return {'error': errmsg}, newreq, newuuid
        try:
            self.workflowApi.instance_operate('provision', async_req=True, sync=False)
        except Exception as ex:
            errmsg = f"Exception during instance operate: {ex}"
            return {'error': errmsg, 'errorlevel': 'senseo'}, newreq, newuuid
        status = {'state': 'CREATE - PENDING', 'configState': 'UNKNOWN'}
        raiseTimeout = False
        while not self._validateState(status, 'create'):
            time.sleep(1)
            status = self.workflowApi.instance_get_status(si_uuid=response['service_uuid'], verbose=True)
            self.timeouts['create'] -= 1
            if self.timeouts['create'] <= 0:
                raiseTimeout = True
                break
        status = self.workflowApi.instance_get_status(si_uuid=response['service_uuid'], verbose=True)
        self.logger.info(f'({self.workerheader}) Final submit status:')
        state = self._validateState(status, 'create')
        response['state'] = state
        self.logger.info(f'({self.workerheader}) provision complete')
        if raiseTimeout:
            errmsg = f'Create timeout. Please check {response["service_uuid"]}'
            return {'error': errmsg, 'state': state, 'response': response}, newreq, newuuid
        return {'finalstate': 'OK', 'state': state, 'response': response}, newreq, newuuid

    @timer_func
    def _cancelwrap(self, si_uuid, force):
        """Wrap the cancel function"""
        try:
            self.workflowApi.instance_operate('cancel', si_uuid=si_uuid, force=force)
        except ValueError as ex:
            self.logger.error(f"({self.workerheader}) Error: {ex}")
            # Check status and return
            status = self.workflowApi.instance_get_status(si_uuid=si_uuid, verbose=True)
            self.logger.info(f'({self.workerheader}) Final cancel status: {status}')
            self.logger.info(status)

    @timer_func
    def cancel(self, serviceuuid, delete=True):
        """Cancel a service instance in SENSE-0"""
        try:
            retDict = self.__cancel(serviceuuid, delete)
            return self._setFinalStats(retDict, None, serviceuuid), retDict.get('error')
        except Exception as ex:
            return self._setFinalStats({'error': f"Exception during Cancel: {ex}"}, None, serviceuuid), ex

    @timer_func
    def __cancel(self, serviceuuid, delete=True):
        """Cancel a service instance in SENSE-0"""
        self.starttime = getUTCnow()
        self._logTiming('CREATE', 'cancel', 'create', getUTCnow())
        status = self.workflowApi.instance_get_status(si_uuid=serviceuuid)
        if 'error' in status:
            return {'error': status['error'], 'response': status}
        if 'CREATE' not in status and 'REINSTATE' not in status and 'MODIFY' not in status:
            return {'error': f"Cannot cancel an instance in '{status}' status..."}
        if 'READY' not in status:
            self._cancelwrap(serviceuuid, 'true')
        else:
            self._cancelwrap(serviceuuid, 'false')
        status = {'state': 'CANCEL - PENDING', 'configState': 'UNKNOWN'}
        while not self._validateState(status, 'cancel'):
            time.sleep(1)
            status = self.workflowApi.instance_get_status(si_uuid=serviceuuid, verbose=True)
            self.timeouts['cancel'] -= 1
            if self.timeouts['cancel'] <= 0:
                return {'error': 'Timeout while validating cancel for instance', 'state': status['state'], 'response': status}

        status = self.workflowApi.instance_get_status(si_uuid=serviceuuid, verbose=True)
        self.logger.info(f'({self.workerheader}) Final cancel status: {status}')
        if self._validateState(status, 'cancel') and delete:
            self.workflowApi.instance_delete(si_uuid=serviceuuid)
            return {'finalstate': 'OK', 'response': status}
        self.logger.info(f'({self.workerheader}) cancel complete')
        return {'finalstate': 'OKNODELETE', 'response': status}

    def run(self, pair):
        """Start loop work"""
        self._reset()
        self._setWorkerHeader(f"{pair[0]}-{pair[1]}")
        if self.checkifJsonExists(pair):
            self.logger.info(f"({self.workerheader}) Skipping: {pair} - Json file already exists")
            return
        self.creatJsonLock(pair)
        cancelled = False
        try:
            self.response['create'], errmsg = self.create(pair)
            self.logger.info(f"({self.workerheader}) response: {self.response}")
            if errmsg:
                raise ValueError(errmsg)
            self.response['cancel'], errmsg = self.cancel(self.response.get('response', {}).get('service_uuid'), True)
            if errmsg:
                raise ValueError(errmsg)
            cancelled = True
        except ValueError as ex:
            self.logger.error(f"({self.workerheader}) Error: {ex}")
            self.logger.error('This will not cancel it if not cancelled. Will keep instance as is')
        except Exception as ex:
            self.logger.error(f"({self.workerheader}) Error: {sys.exc_info()}. Exception: {ex}")
            if self.response and not cancelled:
                try:
                    self.cancel(self.response.get('response', {}).get('service_uuid'), False)
                except Exception as exc:
                    self.logger.error(f"({self.workerheader}) Error: {exc}")
        self.logger.info(f"({self.workerheader}) Final response:")
        self.response['timings'] = self.timings
        self.logger.info(pprint.pformat(self.response))
        # Write response into output file
        self.writeJsonOutput(pair)

    def startwork(self):
        """Process tasks from the queue"""
        while not self.task_queue.empty():
            try:
                pair = self.task_queue.get_nowait()
                self.logger.info(f"Worker {self.workerid} processing pair: {pair}")
                self.run(pair)
                self.task_queue.task_done()
            except queue.Empty:
                break

def getAllGroupedHosts(config):
    """Get all grouped hosts"""
    # TODO - this come from configuration file for now. Later from SENSE-O Discover API
    allEntries = config['entries'].keys()
    uniquePairs = list(combinations(allEntries, 2))
    return uniquePairs


def main(config, starttime, nextRunTime):
    """Main Run"""
    mlogger = getLogger(name='Tester', logFile='/var/log/EndToEndTester/Tester.log')
    unique_pairs = getAllGroupedHosts(config)
    mlogger.info('='*80)
    mlogger.info("Starting multiple threads")
    threads = []
    workers = []
    # Create a queue and populate it with tasks
    task_queue = queue.Queue()
    for pair in unique_pairs:
        task_queue.put(pair)


    if config['totalThreads'] == 1:
        worker = SENSEWorker(task_queue, 0, config)
        worker.startwork()
        return

    for i in range(config['totalThreads']):
        worker = SENSEWorker(task_queue, i, config)
        workers.append(worker)
        thworker = threading.Thread(target=worker.startwork, args=())
        threads.append((thworker, worker))
        thworker.start()
    mlogger.info('join all threads and wait for finish')
    statusout = {'alive': True, 'totalworkers': config['totalThreads'], 'totalqueue': len(unique_pairs),
                 'remainingqueue': task_queue.qsize(), 'updatedate': getUTCnow(), 'insertdate': getUTCnow(),
                 'starttime': starttime, 'nextrun': nextRunTime}
    while any(t[0].is_alive() for t in threads):
        alive = [t[0].is_alive() for t in threads]
        statusout['alive'] = any(alive)
        statusout['remainingqueue'] = task_queue.qsize()
        dumpFileJson(os.path.join(config['workdir'], "testerinfo.run"), statusout)
        mlogger.info(f"Remaining queue size: {task_queue.qsize()}")
        # Write status out file
        dumpFileJson(os.path.join(config['workdir'], "testerinfo" + '.run'), statusout)
        time.sleep(30)

    for thworker, _ in threads:
        thworker.join()

    # Write status file again - everything has finished;
    statusout = {'alive': False, 'totalworkers': 0, 'totalqueue': 0,
                 'remainingqueue': 0, 'updatedate': getUTCnow(), 'insertdate': getUTCnow(),
                 'starttime': starttime, 'nextrun': nextRunTime}
    dumpFileJson(os.path.join(config['workdir'], "testerinfo" + '.run'), statusout)
    mlogger.info('all threads finished')

if __name__ == '__main__':
    logger = getLogger(name='Tester', logFile='/var/log/EndToEndTester/Tester.log')
    yamlconfig = getConfig()
    startimer = getUTCnow()
    nextRun = 0
    while True:
        if nextRun <= getUTCnow():
            logger.info("Timer passed. Running main")
            nextRun = getUTCnow() + yamlconfig['runInterval']
            main(yamlconfig, startimer, nextRun)
        else:
            logger.info(f"Sleeping for {yamlconfig['sleepbetweenruns']} seconds. Timer not passed")
            logger.info(f"Next run: {nextRun}. Current time: {getUTCnow()}. Difference: {nextRun - getUTCnow()}")
            time.sleep(yamlconfig['sleepbetweenruns'])




# from sense.client.discover_api import DiscoverApi # TODO - In future use all hosts;
# Keep as reference code for future to use all hosts;
# TODO Use in Future all hosts;
#def getAllGroupedHosts():
#    """Get all grouped hosts"""
    # workflowApi = WorkflowCombinedApi()
    # client = DiscoverApi()
    # groupedhosts = {}
    # allentries = client.discover_get()
    # for domdict in allentries.get('domains', []):
    #     print(domdict.get('domain_uri'))
    #     print('-'*50)
    #     domain = domdict.get('domain_uri')
    #     sparql = "SELECT DISTINCT ?host ?hostname WHERE { ?site nml:hasNode ?host. ?host nml:hostname  ?hostname. FILTER regex(str(?site),"
    #     sparql += f"'{domain}')"
    #     sparql += "}"
    #     query = {"Hosts": [{"URI": "?host?", "Name": "?hostname?", "sparql-ext": sparql, "required": "true"}]}
    #     try:
    #         allhosts = workflowApi.manifest_create(json.dumps(query))
    #         allhosts['jsonTemplate'] = json.loads(allhosts.get('jsonTemplate'))
    #         for host in allhosts.get('jsonTemplate', {}).get('Hosts', []):
    #             groupedhosts.setdefault(domain, [])
    #             groupedhosts[domain].append(host['URI'])
    #     except Exception as ex:
    #         print(ex)
    # Flatten all lists into a single list
# def main(userargs):
#for pair in unique_pairs:
#    workflowApi = WorkflowCombinedApi()
#    newreq = copy.deepcopy(request)
#    newreq['data']['connections'][0]['terminals'][0]['uri'] = pair[0]
#    newreq['data']['connections'][0]['terminals'][1]['uri'] = pair[1]
#    newreq['alias'] = f'AUTO {pair[0]}-{pair[1]}'
#    workflowApi.si_uuid = None
#    workflowApi.instance_new()
#    response = workflowApi.instance_create(json.dumps(newreq))
#    print(response)
#    status = workflowApi.instance_operate('provision', sync='true')
#    print(f'provision status={status}')
# TODO: In future also do reprovision.
#@timer_func
# def reprovision(self, response, incr):
#     """Reprovision a service instance in SENSE-0"""
#     self.starttime = getUTCnow()
#     self._logTiming('CREATE', f'reprovision{incr}', 'create', getUTCnow())
#     status = self.workflowApi.instance_get_status(si_uuid=response['service_uuid'])
#     if 'error' in status:
#         raise ValueError(status)
#     if 'CANCEL' not in status:
#         raise ValueError(f"({self.workerid}) cannot reprovision an instance in '{status}' status...")
#     if 'READY' not in status:
#         self.workflowApi.instance_operate('reprovision', si_uuid=response['service_uuid'], sync='true', force='true')
#     else:
#         self.workflowApi.instance_operate('reprovision', si_uuid=response['service_uuid'], sync='true')
#     status = {'state': 'REPROVISION - PENDING', 'configState': 'UNKNOWN'}
#     while not self._validateState(status, 'reprovision', incr):
#         time.sleep(1)
#         status = self.workflowApi.instance_get_status(si_uuid=response['service_uuid'], verbose=True)
#         self.timeouts['reprovision'] -= 1
#         if self.timeouts['reprovision'] <= 0:
#             raise ValueError(f'({self.workerid}) reprovision timeout. Please check {response}')
#     print(f'({self.workerid}-{incr}) Final reprovision status:')
#     self._validateState(status, 'reprovision', incr)
#     print(f'({self.workerid}-{incr}) reprovision complete')
