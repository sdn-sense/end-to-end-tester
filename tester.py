import os
import sys
import json
import time
import copy
import pprint
import threading
import math
import argparse
import queue
from itertools import combinations
from yaml import safe_dump as ydump
from sense.common import classwrapper, functionwrapper
from sense.client.discover_api import DiscoverApi
from sense.client.workflow_combined_api import WorkflowCombinedApi

def loadJson(data):
    """Load JSON"""
    if isinstance(data, (dict, list)):
        return data
    try:
        return json.loads(data)
    except json.JSONDecodeError as ex:
        print('Error in loading json dict: %s', ex)
    return {}

def dumpJson(data):
    """Dump JSON"""
    try:
        return json.dumps(data)
    except json.JSONDecodeError as ex:
        print('Error in dumping json dict: %s', ex)
    return {}

request = {
  "service": "dnc",
  "alias": "AutoGOLE-Test-IPv6-Pool",
  "data": {
    "type": "Multi-Path P2P VLAN",
    "connections": [
      {
        "bandwidth": {
          "qos_class": "guaranteedCapped",
          "capacity": "1000"
        },
        "name": "Connection 1",
        "ip_address_pool": {
          "netmask": "/64",
          "name": "AutoGOLE-Test-IPv6-Pool"
        },
        "terminals": [
          {
            "vlan_tag": "any",
            "assign_ip": True,
            "uri": "urn:ogf:network:sense-cern-fabric-testbed.net:2024:frr_s0:e2"
          },
          {
            "vlan_tag": "any",
            "assign_ip": True,
            "uri": "urn:ogf:network:nrp-nautilus.io:2020:k8s-gen5-02.sdsc.optiputer.net:enp168s0np0"
          }
        ],
        "assign_debug_ip": True
      }
    ]
  }
}


@functionwrapper
def argParser():
    """Parse input arguments for the script"""
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--count", action="store", default=5, type=int,
                        help="Count of parallel submissions")
    outargs = parser.parse_args()
    return outargs

def timer_func(func):
    """Decorator function to calculate the execution time of a function"""
    def wrap_func(*args, **kwargs):
        t1 = time.time()
        result = func(*args, **kwargs)
        t2 = time.time()
        print(f'== Function {func.__name__!r} executed in {(t2 - t1):.4f}s')
        print(f'== Function {func.__name__!r} returned: {result}')
        print(f'== Function {func.__name__!r} args: {args}')
        print(f'== Function {func.__name__!r} kwargs: {kwargs}')
        return result
    return wrap_func

@classwrapper
class SENSEWorker():
    """SENSE Worker class"""

    def __init__(self, newlist, workerid=0, result_queue=None):
        self.newlist = newlist
        self.workflowApi = WorkflowCombinedApi()
        self.states = {'create': 'CREATE - READY',
                       'cancel': 'CANCEL - READY',
                       'reprovision': 'REINSTATE - READY'}
        self.timeouts = {'create': 3600,
                         'cancel': 3600,
                         'reprovision': 3600}
        self.timings = {}
        self.starttime = 0
        self.workerid = workerid
        self.result_queue = result_queue

    def _resettimers(self):
        self.timeouts = {'create': 1800,
                         'cancel': 1800,
                         'reprovision': 1800}
        self.timings = {}

    def _logTiming(self, status, call, configstatus, timestamp):
        """Log the timing of the function"""
        self.timings.setdefault(call, {})
        if status not in self.timings[call]:
            self.timings[call][status] = {'entertime': 0, 'configStatus': {}}
            self.timings[call][status]['entertime'] = self.starttime - timestamp
        if configstatus not in self.timings[call][status]['configStatus']:
            self.timings[call][status]['configStatus'][configstatus] = self.starttime - timestamp

    def _getManifest(self, instance):
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
        self.workflowApi.si_uuid = instance['service_uuid']
        response = self.workflowApi.manifest_create(dumpJson(template))
        json_response = loadJson(response)
        if 'jsonTemplate' not in json_response:
            print(f"WARNING: {instance['referenceUUID']} did not receive correct output!")
            print(f"WARNING: Response: {response}")
            return {}
        manifest = loadJson(json_response['jsonTemplate'])
        return manifest

    def _validateState(self, status, call, incr=None):
        """Validate the state of the service instance creation"""
        states = []
        print(f"({self.workerid}-{incr}) status={status.get('state')}")
        print(f"({self.workerid}-{incr}) configStatus={status.get('configState')}")
        callt = call if incr is None else f"{call}{incr}"
        self._logTiming(status.get('state'), callt, status.get('configState'), int(time.time()))
        # If state in failed, raise exception
        if status.get('state') == 'CREATE - FAILED':
            raise ValueError(f'({self.workerid}) create failed. Please check')
        if status.get('state') == self.states[call]:
            states.append(True)
        if status.get('configState') == 'STABLE':
            states.append(True)
        else:
            states.append(False)
        if not states:
            return False
        return all(states)

    @timer_func
    def create(self, pair):
        """Create a service instance in SENSE-0"""
        self.starttime = int(time.time())
        self._logTiming('CREATE', 'create', 'create', int(time.time()))
        self.workflowApi = WorkflowCombinedApi()
        newreq = copy.deepcopy(request)
        newreq['data']['connections'][0]['terminals'][0]['uri'] = pair[0]
        newreq['data']['connections'][0]['terminals'][1]['uri'] = pair[1]
        newreq['alias'] = f'AUTO-{self.workerid} {pair[0].split(":")[-1]}-{pair[1].split(":")[-1]}'
        self.workflowApi.si_uuid = None
        self.workflowApi.instance_new()
        try:
            response = self.workflowApi.instance_create(json.dumps(newreq))
            print(f"({self.workerid}) creating service instance: {response}")
        except ValueError as ex:
            print(f"({self.workerid}) Error: {ex}")
            raise
        self.workflowApi.instance_operate('provision', async_req=True, sync=False)
        status = {'state': 'CREATE - PENDING', 'configState': 'UNKNOWN'}
        while not self._validateState(status, 'create'):
            time.sleep(1)
            status = self.workflowApi.instance_get_status(si_uuid=response['service_uuid'], verbose=True)
            self.timeouts['create'] -= 1
            if self.timeouts['create'] <= 0:
                raise ValueError(f'({self.workerid}) create timeout. Please check {response}')
        status = self.workflowApi.instance_get_status(si_uuid=response['service_uuid'], verbose=True)
        print(f'({self.workerid}) Final submit status:')
        state = self._validateState(status, 'create')
        response['state'] = state
        print(f'({self.workerid}) provision complete')
        # get Manifest
        manifest = self._getManifest(response)
        self.result_queue.put({'response': response, 'manifest': manifest, 'req': newreq})
        return response

    @timer_func
    def _cancelwrap(self, si_uuid, force):
        """Wrap the cancel function"""
        try:
            self.workflowApi.instance_operate('cancel', si_uuid=si_uuid, force=force)
        except ValueError as ex:
            print(f"({self.workerid}) Error: {ex}")
            # Check status and return
            status = self.workflowApi.instance_get_status(si_uuid=si_uuid, verbose=True)
            print(f'({self.workerid}) Final cancel status: {status}')
            print(status)

    @timer_func
    def cancel(self, response, incr):
        """Cancel a service instance in SENSE-0"""
        self.starttime = int(time.time())
        self._logTiming('CREATE', f'cancel{incr}', 'create', int(time.time()))
        status = self.workflowApi.instance_get_status(si_uuid=response['service_uuid'])
        if 'error' in status:
            raise ValueError(status)
        if 'CREATE' not in status and 'REINSTATE' not in status and 'MODIFY' not in status:
            raise ValueError(f"({self.workerid}) cannot cancel an instance in '{status}' status...")
        if 'READY' not in status:
            self._cancelwrap(response['service_uuid'], 'true')
        else:
            self._cancelwrap(response['service_uuid'], 'false')
        status = {'state': 'CANCEL - PENDING', 'configState': 'UNKNOWN'}
        while not self._validateState(status, 'cancel', incr):
            time.sleep(1)
            status = self.workflowApi.instance_get_status(si_uuid=response['service_uuid'], verbose=True)
            self.timeouts['cancel'] -= 1
            if self.timeouts['cancel'] <= 0:
                raise ValueError(f'({self.workerid}) cancel timeout. Please check {response}')
        status = self.workflowApi.instance_get_status(si_uuid=response['service_uuid'], verbose=True)
        print(f'({self.workerid}-{incr}) Final cancel status:')
        self._validateState(status, 'cancel', incr)
        print(f'({self.workerid}-{incr}) cancel complete')

    @timer_func
    def reprovision(self, response, incr):
        """Reprovision a service instance in SENSE-0"""
        self.starttime = int(time.time())
        self._logTiming('CREATE', f'reprovision{incr}', 'create', int(time.time()))
        status = self.workflowApi.instance_get_status(si_uuid=response['service_uuid'])
        if 'error' in status:
            raise ValueError(status)
        if 'CANCEL' not in status:
            raise ValueError(f"({self.workerid}) cannot reprovision an instance in '{status}' status...")
        if 'READY' not in status:
            self.workflowApi.instance_operate('reprovision', si_uuid=response['service_uuid'], sync='true', force='true')
        else:
            self.workflowApi.instance_operate('reprovision', si_uuid=response['service_uuid'], sync='true')
        status = {'state': 'REPROVISION - PENDING', 'configState': 'UNKNOWN'}
        while not self._validateState(status, 'reprovision', incr):
            time.sleep(1)
            status = self.workflowApi.instance_get_status(si_uuid=response['service_uuid'], verbose=True)
            self.timeouts['reprovision'] -= 1
            if self.timeouts['reprovision'] <= 0:
                raise ValueError(f'({self.workerid}) reprovision timeout. Please check {response}')
        print(f'({self.workerid}-{incr}) Final reprovision status:')
        self._validateState(status, 'reprovision', incr)
        print(f'({self.workerid}-{incr}) reprovision complete')

    def startwork(self):
        """Start loop work"""
        for i, pair in enumerate(self.newlist):
            self._resettimers()
            response = {}
            cancelled = False
            try:
                response = self.create(pair)
                print(f"({self.workerid}) response: {response}")
                self.cancel(response, i)
            except:
                if response and not cancelled:
                    self.cancel(response, i)
                print(f"({self.workerid}) Error: {sys.exc_info()}")
            print(f"({self.workerid}) Final timings:")
            pprint.pprint(self.timings)
            # Write timings into yaml file
            os.makedirs('timings', exist_ok=True)
            with open(f'timings/timings-{self.workerid}-{i}.yaml', 'w', encoding="utf-8") as fd:
                fd.write(ydump(self.timings))
        sys.exit(0)

def getAllGroupedHosts():
    """Get all grouped hosts"""
    workflowApi = WorkflowCombinedApi()
    client = DiscoverApi()
    groupedhosts = {}
    allentries = client.discover_get()
    for domdict in allentries.get('domains', []):
        print(domdict.get('domain_uri'))
        print('-'*50)
        domain = domdict.get('domain_uri')
        sparql = "SELECT DISTINCT ?host ?hostname WHERE { ?site nml:hasNode ?host. ?host nml:hostname  ?hostname. FILTER regex(str(?site),"
        sparql += f"'{domain}')"
        sparql += "}"
        query = {"Hosts": [{"URI": "?host?", "Name": "?hostname?", "sparql-ext": sparql, "required": "true"}]}
        try:
            allhosts = workflowApi.manifest_create(json.dumps(query))
            allhosts['jsonTemplate'] = json.loads(allhosts.get('jsonTemplate'))
            for host in allhosts.get('jsonTemplate', {}).get('Hosts', []):
                groupedhosts.setdefault(domain, [])
                groupedhosts[domain].append(host['URI'])
        except Exception as ex:
            print(ex)
    # Flatten all lists into a single list
    allEntries = ["urn:ogf:network:nrp-nautilus-prod.io:2020:k8s-gen4-01.ampath.net",
                  "urn:ogf:network:nrp-nautilus-prod.io:2020:k8s-ceph-01.ampath.net",
                  "urn:ogf:network:tier2.ultralight.org:2024:transfer-16.ultralight.org",
                  "urn:ogf:network:ultralight.org:2013:sandie-6.ultralight.org",
                  "urn:ogf:network:nrp-nautilus.io:2020:node-2-6.sdsc.optiputer.net",
                  "urn:ogf:network:nrp-nautilus.io:2020:k8s-gen5-01.sdsc.optiputer.net",
                  "urn:ogf:network:maxgigapop.net:2013:ptxn-sense-v1.maxgigapop.net",
                  "urn:ogf:network:nrp-nautilus-prod.io:2020:ucsd-nrp.cern.ch",
                  "urn:ogf:network:starlight.org:2022:r740xd4.it.northwestern.edu",
                  "urn:ogf:network:fnal.gov:2023:cmssense2.fnal.gov",
                  "urn:ogf:network:tier2-unl.edu:2024:red-sense-dtn3.unl.edu"]
    #for valueList in groupedhosts.values():
    #    import pdb; pdb.set_trace()
    #    allEntries.extend(valueList)
    uniquePairs = list(combinations(allEntries, 2))
    return uniquePairs


def main(userargs):
    """Main Run"""
    unique_pairs = getAllGroupedHosts()
    print('='*80)
    print("Starting multiple threads")
    threads = []
    result_queue = queue.Queue()
    totalThreads = userargs.count
    totalPerThread = math.ceil(len(unique_pairs) / totalThreads)
    newlist = [unique_pairs[i:i+totalPerThread] for i in range(0, len(unique_pairs), totalPerThread)]

    if totalThreads == 1:
        worker = SENSEWorker(newlist[0], 0, result_queue)
        worker.startwork()
        return

    for i in range(totalThreads):
        worker = SENSEWorker(newlist[i], i, result_queue)
        thworker = threading.Thread(target=worker.startwork, args=())
        threads.append(thworker)
        thworker.start()
    print('join all threads and wait for finish')
    for t in threads:
        t.join()
    print('all threads finished')
    # Write the result_queue to a file
    os.makedirs('results', exist_ok=True)
    # add timestamp to the file
    fname = f'results/results.yaml-{time.time()}'
    with open(fname, 'w', encoding="utf-8") as fd:
        results = []
        while not result_queue.empty():
            results.append(result_queue.get())
        fd.write(ydump(results))
    print(f"Results written to {fname}")
    print('='*80)

if __name__ == '__main__':
    inargs = argParser()
    main(inargs)

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
