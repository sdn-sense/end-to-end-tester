#!/usr/bin/env python3
# pylint: disable=line-too-long
"""
Class for interacting with SENSE SiteRMs
"""
import time
from EndToEndTester.utilities import loadJson, getUTCnow
from sense.client.siterm.debug_api import DebugApi


class SiteRMApi:
    """Class for interacting with SENSE-0 API"""

    def __init__(self, **kwargs):
        self.config = kwargs.get("config")
        self.logger = kwargs.get("logger")
        self.siterm_debug = DebugApi()

    @staticmethod
    def _sr_all_keys_match(action, newaction):
        return all(newaction.get(key) == action.get(key) for key in newaction)

    def _sr_get_all_hosts(self, **kwargs):
        """Get all hosts from manifest"""
        allHosts, allIPs = [], {}
        for _idx, item in enumerate(kwargs.get("manifest", {}).get("Ports", [])):
            # Switch IPs
            for key, defval in [
                ("IPv4", ["?ipv4?", "?port_ipv4?"]),
                ("IPv6", ["?ipv6?", "?port_ipv6?"]),
            ]:
                if item.get(key) and item[key] not in defval:
                    allIPs.setdefault(key, [])
                    allIPs[key].append(item[key].split("/")[0])
            # Host IPs and all Hosts
            for hostdata in item.get("Host", []):
                if item.get("Vlan"):
                    hostdata["vlan"] = f"vlan.{item['Vlan']}"
                allHosts.append(hostdata)
                # Check if IPv6 or IPv4 is defined
                for key, defval in [("IPv4", "?ipv4?"), ("IPv6", "?ipv6?")]:
                    if hostdata.get(key) and hostdata[key] not in defval:
                        allIPs.setdefault(key, [])
                        allIPs[key].append(hostdata[key].split("/")[0])
        return allHosts, allIPs

    def sr_get_debug_actions(self, **kwargs):
        """Get all debug actions for a site and hostname"""
        allDebugActions = []
        for key in ["new", "active"]:
            jsonOut = {}
            out = self.siterm_debug.get_all_debug_hostname(
                sitename=kwargs.get("sitename"),
                hostname=kwargs.get("hostname"),
                state=key,
            )
            allitems = []
            if out and out[0]:
                allitems = loadJson(out[0])
            for tmpitem in allitems:
                jsonOut = loadJson(tmpitem)
                print(f"Debug action found: {jsonOut}")
                if not jsonOut.get("id"):
                    self.logger.warning(f"Debug action {jsonOut} has no ID. Skipping.")
                    continue
                ditem = self.siterm_debug.get_debug(
                    sitename=kwargs.get("sitename"), id=jsonOut["id"]
                )
                if ditem and ditem[0]:
                    ditem = ditem[0]
                    ditem["requestdict"] = loadJson(ditem["requestdict"])
                allDebugActions.append(ditem)
        return allDebugActions

    def sr_submit_ping(self, **kwargs):
        """Submit a ping test to the SENSE-SiteRM API"""
        # pylint: disable=too-many-nested-blocks,too-many-locals
        self.logger.info("Start check for ping test if needed")
        hosts, allIPs = self._sr_get_all_hosts(**kwargs)
        # based on our variables;
        ping_out = {"errors": [], "results": [], "hostips": {}, "ipvlans": {}}
        for host in hosts:
            # Check if IPv6 or IPv4 is defined
            for key, defval in [("IPv4", "?ipv4?"), ("IPv6", "?ipv6?")]:
                if host.get(key) and host[key] != defval:
                    hostspl = host.get("Name").split(":")
                    ipaddr = host.get(key).split("/")[0]
                    ping_out["hostips"].setdefault(hostspl[1], ipaddr)
                    ping_out["ipvlans"].setdefault(
                        ipaddr,
                        host["Interface"] if not host.get("vlan") else host["vlan"],
                    )
                    try:
                        allDebugActions = self.sr_get_debug_actions(
                            **{"sitename": hostspl[0], "hostname": hostspl[1]}
                        )
                    except Exception as ex:
                        errmsg = f"Failed to get debug actions for {hostspl[0]}:{hostspl[1]}: {ex}"
                        ping_out["errors"].append(errmsg)
                        self.logger.error(errmsg)
                        allDebugActions = []
                        continue
                    for ip in allIPs.get(key, []):
                        if ipaddr == ip:
                            # We ignore ourself. No need to ping ourself
                            continue
                        # Loop all debug actions and check if the action is already in the list of actions
                        newaction = {
                            "hostname": hostspl[1],
                            "type": "rapid-ping",
                            "sitename": hostspl[0],
                            "ip": ip,
                            "packetsize": kwargs.get("packetsize", 56),
                            "onetime": True,
                            "interval": kwargs.get("interval", 5),
                            "interface": host["Interface"]
                            if not host.get("vlan")
                            else host["vlan"],
                            "time": kwargs.get("time", 60),
                        }
                        actionPresent = False
                        for action in allDebugActions:
                            if self._sr_all_keys_match(
                                action.get("requestdict"), newaction
                            ):
                                self.logger.info(
                                    "Action already present. Monitor the existing action"
                                )
                                newaction["submit_time"] = action.get("insertdate")
                                newaction["submit_out"] = {
                                    "ID": action.get("id"),
                                    "Status": "OK",
                                }
                                ping_out["results"].append(newaction)
                                actionPresent = True
                                break
                        if not actionPresent:
                            repeat = 3
                            tmpout = []
                            while repeat > 0:
                                self.logger.info(
                                    f"Submitting ping test for {newaction}"
                                )
                                out = self.siterm_debug.submit_ping(**newaction)
                                # Check if out [1] is True, which means the action was submitted successfully
                                # Retry up to 3 times, and
                                if len(out) == 3 and out[1] is True:
                                    newaction["submit_time"] = getUTCnow()
                                    newaction["submit_out"] = out[0]
                                    self.logger.info(
                                        f"Submitted ping test for {newaction}: {out}"
                                    )
                                    ping_out["results"].append(newaction)
                                    repeat = 0
                                else:
                                    errmsg = f"Failed to submit ping test for {newaction}: {out}"
                                    self.logger.error(errmsg)
                                    tmpout.append(out)
                                    repeat -= 1
                                    if repeat == 0:
                                        ping_out["submit_errors"] = tmpout
                                        errmsg = f"Failed to submit ping test after 3 attempts. Last error: {errmsg}"
                                        self.logger.error(errmsg)
                                        return ping_out, False
                                    time.sleep(10)
        return ping_out, True

    def monitorping(self, **kwargs):
        """Monitor ping tests"""
        output = {"errors": [], "results": []}
        monitorendpoints = []
        for item in kwargs.get("pingresults", {}).get("submit", {}).get("results", []):
            sitename = item.get("sitename")
            pingid = item["submit_out"].get("ID")
            status = item["submit_out"].get("Status")
            if status == "OK":
                # Submission state was ok;
                monitorendpoints.append({"id": pingid, "sitename": sitename})
            else:
                output["results"].append(
                    {"Status": "FailedSubmit", "id": pingid, "sitename": sitename}
                )
        # Now we loop over monitorendpoints and check the status
        monitor = bool(monitorendpoints)
        starttime = getUTCnow()
        while monitor:
            delitems = []
            for idx, endpoint in enumerate(monitorendpoints):
                out = self.siterm_debug.get_debug(
                    sitename=endpoint["sitename"], id=endpoint["id"]
                )
                self.logger.debug(
                    f"Checking ping test {endpoint['sitename']}:{endpoint['id']}. Output: {out}"
                )
                if out[0]["state"] not in ["new", "active"]:
                    self.logger.info(
                        f'Ping test {endpoint["sitename"]}:{endpoint["id"]} finished'
                    )
                    self.logger.debug(
                        f'Ping test {endpoint["sitename"]}:{endpoint["id"]} finished with {out[0]}'
                    )
                    delitems.append(idx)
                    output["results"].append(out[0])
                if getUTCnow() - starttime > 600:
                    self.logger.error(
                        f"Timeout to get ping finished for {sitename}:{pingid}"
                    )
                    self.logger.debug(
                        f"Timeout to get ping finished for {sitename}:{pingid}. Debug: {out[0]}"
                    )
                    output["errors"].append(
                        f"Timeout to get ping finished for {sitename}:{pingid}"
                    )
                    delitems.append(idx)
                    output["results"].append(out[0])
                time.sleep(1)
            for idx in sorted(delitems, reverse=True):
                del monitorendpoints[idx]
            if not monitorendpoints:
                break
        return output

    def testPing(self, finalReturn):
        """Test Ping"""
        finalReturn.setdefault("pingresults", {"submit": {}, "final": {}})
        pingSubmitResults, exitCode = self.sr_submit_ping(**finalReturn)
        finalReturn["pingresults"]["submit"] = pingSubmitResults
        if exitCode:
            pingStatusResults = self.monitorping(**finalReturn)
            finalReturn["pingresults"]["final"] = pingStatusResults
        return finalReturn
