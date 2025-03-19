#!/usr/bin/env python3
# pylint: disable=line-too-long
"""DB Backend SQL Calls to databases.
Title                   : end-to-end-tester
Author                  : Justas Balcas
Email                   : jbalcas (at) es.net
@Copyright              : Copyright (C) 2025 ESnet
Date                    : 2025/03/14
"""
# CREATE TABLES
create_requests = """CREATE TABLE IF NOT EXISTS requests (
    id SERIAL PRIMARY KEY,
    uuid VARCHAR(255) NOT NULL,
    port1 VARCHAR(255) NOT NULL,
    port2 VARCHAR(255) NOT NULL,
    finalstate INTEGER NOT NULL CHECK (finalstate IN (0,1)),
    pathfindissue INTEGER NOT NULL CHECK (pathfindissue IN (0,1)),
    requesttype VARCHAR(64) NOT NULL,
    insertdate TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updatedate TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    fileloc VARCHAR(4096),
    site1 VARCHAR(64) NOT NULL,
    site2 VARCHAR(64) NOT NULL,
    failure VARCHAR(4096),
    UNIQUE(uuid)
);"""
create_actions = """CREATE TABLE IF NOT EXISTS actions (
    id SERIAL PRIMARY KEY,
    uuid VARCHAR(255) NOT NULL,
    action VARCHAR(255) NOT NULL,
    site1 VARCHAR(64) NOT NULL,
    site2 VARCHAR(64) NOT NULL,
    insertdate TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updatedate TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);"""
create_verification = """CREATE TABLE IF NOT EXISTS verification (
    id SERIAL PRIMARY KEY,
    uuid VARCHAR(255) NOT NULL,
    site VARCHAR(64) NOT NULL,
    action VARCHAR(255) NOT NULL,
    site1 VARCHAR(64) NOT NULL,
    site2 VARCHAR(64) NOT NULL,
    netstatus VARCHAR(255) NOT NULL,
    urn VARCHAR(4096) NOT NULL,
    verified INTEGER NOT NULL CHECK (verified IN (0,1)),
    insertdate TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updatedate TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);"""
create_requeststates = """CREATE TABLE IF NOT EXISTS requeststates (
    id SERIAL PRIMARY KEY,
    uuid VARCHAR(255) NOT NULL,
    state VARCHAR(255) NOT NULL,
    configstate VARCHAR(255) NOT NULL,
    action VARCHAR(255) NOT NULL,
    site1 VARCHAR(64) NOT NULL,
    site2 VARCHAR(64) NOT NULL,
    insertdate TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updatedate TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);"""

create_runnerinfo = """CREATE TABLE IF NOT EXISTS runnerinfo (
    id SERIAL PRIMARY KEY,
    alive BOOLEAN NOT NULL,
    totalworkers INTEGER NOT NULL,
    totalqueue INTEGER NOT NULL,
    remainingqueue INTEGER NOT NULL,
    lockedrequests INTEGER NOT NULL,
    updatedate TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    insertdate TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    starttime TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    nextrun TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);"""


# INSERT INTO TABLES
insert_requests = """INSERT INTO requests (uuid, port1, port2, finalstate, pathfindissue, requesttype, insertdate, updatedate, fileloc, site1, site2, failure)
VALUES (%(uuid)s, %(port1)s, %(port2)s, %(finalstate)s, %(pathfindissue)s, %(requesttype)s, FROM_UNIXTIME(%(insertdate)s),FROM_UNIXTIME(%(updatedate)s), %(fileloc)s, %(site1)s, %(site2)s, %(failure)s)"""
insert_actions = """INSERT INTO actions (uuid, action, site1, site2, insertdate, updatedate)
VALUES (%(uuid)s, %(action)s, %(site1)s, %(site2)s,  FROM_UNIXTIME(%(insertdate)s), FROM_UNIXTIME(%(updatedate)s))"""
insert_verification = """INSERT INTO verification (uuid, site, action, site1, site2, netstatus, urn, verified, insertdate, updatedate)
VALUES (%(uuid)s, %(site)s, %(action)s, %(site1)s, %(site2)s, %(netstatus)s, %(urn)s, %(verified)s, FROM_UNIXTIME(%(insertdate)s), FROM_UNIXTIME(%(updatedate)s))"""
insert_requeststates = """INSERT INTO requeststates (uuid, state, configstate, action, site1, site2, entertime, insertdate, updatedate)
VALUES (%(uuid)s, %(state)s, %(configstate)s, %(action)s,%(site1)s, %(site2)s, FROM_UNIXTIME(%(entertime)s), FROM_UNIXTIME(%(insertdate)s), FROM_UNIXTIME(%(updatedate)s))"""
insert_runnerinfo = """INSERT INTO runnerinfo (alive, totalworkers, totalqueue, remainingqueue, lockedrequests, updatedate, insertdate, starttime, nextrun)
VALUES (%(alive)s, %(totalworkers)s, %(totalqueue)s, %(remainingqueue)s, %(lockedrequests)s, FROM_UNIXTIME(%(updatedate)s), FROM_UNIXTIME(%(insertdate)s), FROM_UNIXTIME(%(starttime)s), FROM_UNIXTIME(%(nextrun)s))"""


# SELECT FROM TABLES
get_requests = """SELECT * FROM requests"""
get_actions = """SELECT * FROM actions"""
get_verification = """SELECT * FROM verification"""
get_requeststates = """SELECT * FROM requeststates"""
get_runnerinfo = """SELECT * FROM runnerinfo"""

# UPDATE TABLES
update_requests = "UPDATE requests SET updatedate = FROM_UNIXTIME(%(updatedate)s), fileloc = %(fileloc)s WHERE uuid = %(uuid)s"
update_runnerinfo = "UPDATE runnerinfo SET alive = %(alive)s, totalworkers = %(totalworkers)s, lockedrequests = %(lockedrequests)s, totalqueue =  %(totalqueue)s, remainingqueue =  %(remainingqueue)s, updatedate = FROM_UNIXTIME(%(updatedate)s), starttime = FROM_UNIXTIME(%(starttime)s), nextrun = FROM_UNIXTIME(%(nextrun)s) WHERE id = %(id)s"

# DELETE FROM TABLES
delete_models = "DELETE FROM requests"
delete_deltas = "DELETE FROM actions"
delete_delta_connections = "DELETE FROM verification"
delete_requeststates = "DELETE FROM requeststates"
