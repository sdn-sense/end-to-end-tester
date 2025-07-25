#!/usr/bin/env python3
"""Database starter to create and update database"""
from time import sleep
import mariadb # type: ignore
from EndToEndTester.DBBackend import dbinterface
from EndToEndTester.dbcalls import GBCONFIGSTATES, GBCREATESTATES

class DBStarter:
    """Database starter class"""
    def __init__(self):
        self.db = dbinterface()

    def dbready(self):
        """Check if the database is ready"""
        try:
            self.db.db.execute("SELECT 1")
        except mariadb.OperationalError as ex:
            print(f"Error executing SQL: {ex}")
            return False
        return True

    def dboptimize(self):
        """Optimize the database"""
        print("Optimizing database")
        try:
            out = self.db.db.execute_get("""SELECT CONCAT('CREATE TABLE ', table_name, '_new LIKE ', table_name, '; ',
                                                          'INSERT INTO ', table_name, '_new SELECT * FROM ', table_name, '; ',
                                                          'RENAME TABLE ', table_name, ' TO ', table_name, '_old, ',
                                                                           table_name, '_new TO ', table_name, '; ',
                                                          'DROP TABLE ', table_name, '_old; '
                                                         ) AS migration_commands
                                            FROM information_schema.tables
                                            WHERE table_schema = 'endtoend';""")
            for row in out[2]:
                print("Executing SQL Command:", row[0])
                for item in row[0].split(';'):
                    if item.strip():
                        self.db.db.execute(item.strip())
        except mariadb.OperationalError as ex:
            print(f"Error executing SQL: {ex}")
            return False
        return True

    def populatenewstates(self):
        """Populate new states"""
        print('Populate new states. Delete old ones, and put new ones from code-base')
        # Delete all states in database;
        for item in self.db.get("stateorder", limit=1000):
            self.db.delete("stateorder", [["orderid", item["orderid"]]])
        # Now we readd all new ones;
        counter = 1
        for stfind in GBCREATESTATES:
            for configstate in GBCONFIGSTATES:
                self.db.insert('stateorder', [{'state': stfind[0], 'action': stfind[1],
                                               'configstate': configstate, 'orderid': counter}])
                counter += 1

    def start(self):
        """Start the database creation"""
        while not self.dbready():
            print("Database not ready, waiting for 1 second. See error above. If continous, check the mariadb process.")
            sleep(1)
        self.db.createdb()
        self.dboptimize()
        self.populatenewstates()
        print("Database ready")


if __name__ == "__main__":
    dbclass = DBStarter()
    dbclass.start()
    while True:
        sleep(3600)
