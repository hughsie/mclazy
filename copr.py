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

def build_in_copr(copr, pkgs):
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
        return None
    else:
        print(output['message'])

    return output['id']


def wait_for_builds(builds_in_progress, db):
    rc = True
    for pkg in builds_in_progress:
        print_info("Waiting for %s [%i]" % (pkg.get_nvr(), pkg.build_id))
    try:
        while len(builds_in_progress) > 0:
            for pkg in builds_in_progress:
                (ret, status) = copr_cli.subcommands._fetch_status(pkg.build_id)
                if not ret:
                    print_fail("Unable to get build status for %i" % pkg.build_id)
                    continue
                if status == 'succeeded':
                    # add to database
                    builds_in_progress.remove(pkg)
                    print_info("build %s [%i] succeeded" % (pkg.name, pkg.build_id))
                    db.add_build(pkg)
                elif status == 'running':
                    print_info("build %s [%i] running" % (pkg.name, pkg.build_id))
                elif status == 'failed':
                    builds_in_progress.remove(pkg)
                    print_fail("build %s [%i] failed" % (pkg.name, pkg.build_id))
                    rc = False
                time.sleep(1)
            time.sleep(10)
    except KeyboardInterrupt:
        rc = False
    return rc

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

    current_depsolve_level = 0;
    builds_in_progress = []

    for item in data.items:

        if current_depsolve_level != item._depsolve_order:
            if len(builds_in_progress):
                print("Waiting for depsolve level %i" % current_depsolve_level)
                rc = wait_for_builds(builds_in_progress, db)
                if not rc:
                    print_fail("Aborting")
                    break
            current_depsolve_level = item._depsolve_order
            print("Now running depsolve level %i" % current_depsolve_level)

        # get the latest build from koji
        pkg = koji.get_newest_build(MCLAZY_BRANCH_TARGET, item.pkgname)
        print("Latest version of %s in %s: %s" % (item.pkgname, MCLAZY_BRANCH_TARGET, pkg.get_nvr()))

        # has this build been submitted?
        if db.build_exists(pkg):
            print("Already built in copr")
            continue

        # does this version already exist?
        pkg_stable = koji.get_newest_build(MCLAZY_BRANCH_SOURCE, item.pkgname)
        if pkg_stable:
            print("Latest version in %s: %s" % (MCLAZY_BRANCH_SOURCE, pkg_stable.get_nvr()))
            if pkg.version == pkg_stable.version:
                print("Already exists same version")
                continue

        # submit to copr
        print("Submitting URL " + pkg.get_url())
        pkg.build_id = build_in_copr(MCLAZY_COPR_ID, [pkg.get_url()])
        if not pkg.build_id:
            print_fail("build")
            break
        print("Adding build " + str(pkg.build_id))
        builds_in_progress.append(pkg)


if __name__ == "__main__":
    main()
