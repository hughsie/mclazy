#!/usr/bin/python
# Licensed under the GNU General Public License Version 2
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

# Copyright (C) 2014
#    Richard Hughes <richard@hughsie.com>

import koji
import sqlite3
import time
import requests

import copr_cli.subcommands
from xml.etree.ElementTree import ElementTree

from modules import ModulesXml
from package import Package

MCLAZY_COPR_ID = 'f20-gnome-3-12'
MCLAZY_COPR_DATABASE = './copr.db'
MCLAZY_KOJI_HUB = 'http://koji.fedoraproject.org/kojihub/'
MCLAZY_BRANCH_TARGET = 'rawhide'
MCLAZY_BRANCH_SOURCE = 'f20'

COLOR_OKBLUE = '\033[94m'
COLOR_OKGREEN = '\033[92m'
COLOR_WARNING = '\033[93m'
COLOR_FAIL = '\033[91m'
COLOR_ENDC = '\033[0m'

class LocalDb:
    def __init__(self):
        self.con = sqlite3.connect(MCLAZY_COPR_DATABASE)
        cur = self.con.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS builds(timestamp INTEGER PRIMARY KEY ASC, nvr TEXT)")
        cur.close()
        self.con.commit()

    def __del__(self):
        self.con.close()

    def build_exists(self, pkg):
        cur = self.con.cursor()
        cur.execute("SELECT * FROM builds WHERE nvr = '%s'" % pkg.get_nvr())
        rows = cur.fetchall()
        cur.close()
        return len(rows) > 0

    def add_build(self, pkg):
        if self.build_exists(pkg):
            print "pkg already exists!"
            return;
        cur = self.con.cursor()
        ts = int(time.time())
        cur.execute("INSERT INTO builds(timestamp,nvr) VALUES(?,?)", (ts, pkg.get_nvr()))
        cur.close()
        self.con.commit()

class Koji:
    def __init__(self):
        self.session = koji.ClientSession(MCLAZY_KOJI_HUB)

    def get_newest_build(self, branch, pkgname):
        builds = self.session.getLatestRPMS(branch, package=pkgname, arch='src')
        if len(builds[0]) == 0:
            return None
        latest = builds[0][0]
        pkg = Package()
        pkg.name = latest['name']
        pkg.version = latest['version']
        pkg.release = latest['release']
        return pkg

def build_in_copr(copr, pkgs, wait=True):
    """ Build a new package into a given copr. """
    user = copr_cli.subcommands.get_user()
    copr_api_url = copr_cli.subcommands.get_api_url()
    URL = '{0}/coprs/{1}/{2}/new_build/'.format(
        copr_api_url,
        user['username'],
        copr)

    data = {'pkgs': ' '.join(pkgs),
            'memory': None,
            'timeout': None
            }

    req = requests.post(URL,
                        auth=(user['login'], user['token']),
                        data=data)
    output = copr_cli.subcommands._get_data(req, user, copr)
    if output is None:
        return False
    else:
        print(output['message'])

    if wait:
        print_info("Watching build: %i" % output['id'])
        prevstatus = None
        try:
            while True:
                (ret, status) = copr_cli.subcommands._fetch_status(output['id'])
                if not ret:
                    print_fail("Unable to get build status")
                    return False

                if prevstatus != status:
                    prevstatus = status

                if status == 'succeeded':
                    return True
                if status == 'failed':
                    return False

                time.sleep(10)

        except KeyboardInterrupt:
            pass

    return True

def print_info(text):
    print COLOR_OKBLUE + "    INFO: " + text + COLOR_ENDC

def print_fail(text):
    print COLOR_FAIL + "    FAILED: " + text + COLOR_ENDC

def main():

    # parse the configuration file
    data = ModulesXml("./modules.xml")
    print("Depsolving moduleset...")
    if not data.depsolve():
        print_fail("Failed to depsolve")
        return

    koji = Koji()
    db = LocalDb()

    pkg_names = data.get_pkgnames()
    for pkg_name in pkg_names:

        print("Looking for %s" % pkg_name)

        # get the latest build from koji
        pkg = koji.get_newest_build(MCLAZY_BRANCH_TARGET, pkg_name)
        print("Latest version in %s: %s" % (MCLAZY_BRANCH_TARGET, pkg.get_nvr()))

        # has this build been submitted?
        if db.build_exists(pkg):
            print("Already built in copr!")
            continue

        # does this version already exist?
        pkg_stable = koji.get_newest_build(MCLAZY_BRANCH_SOURCE, pkg_name)
        if pkg_stable:
            print("Latest version in %s: %s" % (MCLAZY_BRANCH_SOURCE, pkg_stable.get_nvr()))
            if pkg.version == pkg_stable.version:
                print("Already exists same version!")
                continue

        # submit to copr
        print("Submitting URL " + pkg.get_url())
        rc = build_in_copr(MCLAZY_COPR_ID, [pkg.get_url()])
        if rc != True:
            print_fail("build")
            break

        # add to database
        db.add_build(pkg)

if __name__ == "__main__":
    main()
