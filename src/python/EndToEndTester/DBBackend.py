#!/usr/bin/env python3
"""DB Backend for communication with database. Mainly we use mariadb
Title                   : end-to-end-tester
Author                  : Justas Balcas
Email                   : jbalcas (at) es.net
@Copyright              : Copyright (C) 2025 ESnet
Date                    : 2025/03/14
"""
import os
from contextlib import contextmanager
from datetime import datetime, timezone
import mariadb  # type: ignore
from EndToEndTester import dbcalls


def getUTCnow():
    """Get UTC Time."""
    return int(datetime.now(timezone.utc).timestamp())


def loadEnv(envFile='/etc/endtoend-mariadb'):
    """Load Environment file and export variables"""
    if not os.path.isfile(envFile):
        return
    with open(envFile, 'r', encoding='utf-8') as fd:
        for line in fd:
            if line.startswith('#') or not line.strip():
                continue
            key, val = line.strip().split('=', 1)
            if not os.environ.get(key):
                os.environ[key] = val


class DBBackend():
    """Database Backend class."""
    def __init__(self):
        loadEnv()
        self.mpass = os.getenv('MARIA_DB_PASSWORD')
        self.muser = os.getenv('MARIA_DB_USER', 'root')
        self.mhost = os.getenv('MARIA_DB_HOST', 'localhost')
        self.mport = int(os.getenv('MARIA_DB_PORT', '3306'))
        self.mdb = os.getenv('MARIA_DB_DATABASE', 'endtoend')
        self.autocommit = os.getenv('MARIA_DB_AUTOCOMMIT', 'True') in ['True', 'true', '1']

    def __enter__(self):
        """Enter the runtime context related to this object."""
        self.checkdbconnection()
        return self

    @contextmanager
    def get_connection(self):
        """Open connection and cursor."""
        conn = None
        cursor = None
        try:
            conn = mariadb.connect(user=self.muser,
                                   password=self.mpass,
                                   host=self.mhost,
                                   port=self.mport,
                                   database=self.mdb,
                                   autocommit=self.autocommit)
            cursor = conn.cursor()
            yield conn, cursor
        except Exception as e:
            print(f"Error establishing database connection: {e}")
            raise e
        finally:
            if conn:
                conn.close()


    def checkdbconnection(self, retry=True):
        """
        Check if the database connection is alive.
        """
        try:
            with self.get_connection() as (_conn, cursor):
                cursor.execute("SELECT 1")
                result = cursor.fetchone()
                if result and result[0] == 1:
                    return True
            if retry:
                return self.checkdbconnection(retry=False)
        except Exception as ex:
            raise ex
        raise Exception(f"Error while checking the database connection: {result}")

    def createdb(self):
        """Create database."""
        self.checkdbconnection()
        for argname in dir(dbcalls):
            if argname.startswith('create_'):
                print(f'Call to create {argname}')
                with self.get_connection() as (_conn, cursor):
                    cursor.execute(getattr(dbcalls, argname))

    def cleandbtable(self, dbtable):
        """Clean only specific table if available"""
        self.checkdbconnection()
        for argname in dir(dbcalls):
            if argname == f'delete_{dbtable}':
                print(f'Call to clean from {argname}')
                with self.get_connection() as (_conn, cursor):
                    cursor.execute(getattr(dbcalls, argname))

    def cleandb(self):
        """Clean database."""
        self.checkdbconnection()
        for argname in dir(dbcalls):
            if argname.startswith('delete_'):
                print(f'Call to clean from {argname}')
                with self.get_connection() as (_conn, cursor):
                    cursor.execute(getattr(dbcalls, argname))


    def execute_get(self, query):
        """GET Execution."""
        self.checkdbconnection()
        alldata = []
        colname = []
        with self.get_connection() as (_conn, cursor):
            try:
                cursor.execute(query)
                colname = [tup[0] for tup in cursor.description]
                alldata = cursor.fetchall()
            except Exception as ex:
                raise ex
        return 'OK', colname, alldata

    def execute_ins(self, query, values):
        """INSERT Execute."""
        self.checkdbconnection()
        lastID = -1
        with self.get_connection() as (conn, cursor):
            try:
                for item in values:
                    cursor.execute(query, item)
                    lastID = cursor.lastrowid
            except mariadb.Error as ex:
                print(f'MariaDBError. Ex: {ex}')
                conn.rollback()
            except Exception as ex:
                print(f'Got Exception {ex} ')
                conn.rollback()
                raise ex
        return 'OK', '', lastID

    def execute_del(self, query, values):
        """DELETE Execute."""
        self.checkdbconnection()
        del values
        with self.get_connection() as (conn, cursor):
            try:
                cursor.execute(query)
            except Exception as ex:
                print(f'Got Exception {ex} ')
                conn.rollback()
                raise ex
        return 'OK', '', ''

    def execute(self, query):
        """Execute query."""
        self.checkdbconnection()
        with self.get_connection() as (conn, cursor):
            try:
                cursor.execute(query)
            except mariadb.InterfaceError as ex:
                print(f'Got Exception {ex} ')
            except Exception as ex:
                print(f'Got Exception {ex} ')
                conn.rollback()
                raise ex
        return 'OK', '', ''

class dbinterface():
    """Database interface."""
    def __init__(self):
        self.db = DBBackend()
        self.callStart = None
        self.callEnd = None

    def createdb(self):
        """Create Database."""
        self.db.createdb()

    def _setStartCallTime(self, calltype):
        """Set Call Start timer."""
        del calltype
        self.callStart = float(getUTCnow())

    def _setEndCallTime(self, _calltype, _callExit):
        """Set Call End timer."""
        self.callEnd = float(getUTCnow())

    @staticmethod
    def getcall(callaction, calltype):
        """Get call from ALL available ones."""
        callquery = ""
        try:
            callquery = getattr(dbcalls, f'{callaction}_{calltype}')
        except AttributeError as ex:
            print('Called %s_%s, but got exception %s', callaction, calltype, ex)
            raise ex
        return callquery

    # =====================================================
    #  HERE GOES GET CALLS
    # =====================================================

    def _caller(self, origquery, limit=None, orderby=None, search=None):
        """Modifies get call and include WHER/ORDER/LIMIT."""
        query = ""
        if search:
            first = True
            for item in search:
                if not item:
                    continue
                if first:
                    query = "WHERE "
                    first = False
                else:
                    query += "AND "
                query += f'{item[0]} = "{item[1]}" '
        if orderby:
            query += f"ORDER BY {orderby[0]} {orderby[1]} "
        if limit:
            query += f"LIMIT {limit}"
        fullquery = f"{origquery} {query}"
        return self.db.execute_get(fullquery)

    def get(self, calltype, limit=None, search=None, orderby=None, mapping=True):
        """GET Call for APPs."""
        self._setStartCallTime(calltype)
        callExit, colname, dbout = self._caller(self.getcall('get', calltype), limit, orderby, search)
        self._setEndCallTime(calltype, callExit)
        out = []
        if mapping:
            for item in dbout:
                out.append(dict(list(zip(colname, list(item)))))
            return out
        return dbout

    # =====================================================
    #  HERE GOES INSERT CALLS
    # =====================================================

    def insert(self, calltype, values):
        """INSERT call for APPs."""
        self._setStartCallTime(calltype)
        out = self.db.execute_ins(self.getcall('insert', calltype), values)
        self._setEndCallTime(calltype, out[0])
        return out

    # =====================================================
    #  HERE GOES UPDATE CALLS
    # =====================================================

    def update(self, calltype, values):
        """UPDATE Call for APPs."""
        self._setStartCallTime(calltype)
        out = self.db.execute_ins(self.getcall('update', calltype), values)
        self._setEndCallTime(calltype, out[0])
        return out

    # =====================================================
    #  HERE GOES DELETE CALLS
    # =====================================================

    def delete(self, calltype, values):
        """DELETE Call for APPs."""
        query = ""
        if values:
            first = True
            for item in values:
                if first:
                    query = "WHERE "
                else:
                    query += "AND "
                first = False
                query += f'{item[0]} = "{item[1]}" '
        fullquery = f"{self.getcall('delete', calltype)} {query}"
        self._setStartCallTime(calltype)
        out = self.db.execute_del(fullquery, None)
        self._setEndCallTime(calltype, out[0])
        return out

    # =====================================================
    #  HERE GOES CLEAN CALLS
    # =====================================================
    def _clean(self, calltype, values):
        """Database Clean Up"""
        del calltype, values
        self.db.cleandb()

    def _cleantable(self, calltype, values):
        """Clean specific table"""
        del values
        self.db.cleandbtable(calltype)
