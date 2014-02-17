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
import copr_cli.subcommands
from xml.etree.ElementTree import ElementTree

MCLAZY_COPR_ID = 'f20-gnome-3-12'
MCLAZY_COPR_DATABASE = './copr.db'
MCLAZY_KOJI_INSTANCE = 'http://kojipkgs.fedoraproject.org/packages/'
MCLAZY_KOJI_HUB = 'http://koji.fedoraproject.org/kojihub/'
MCLAZY_BRANCH_INHERIT = 'rawhide'

COLOR_OKBLUE = '\033[94m'
COLOR_OKGREEN = '\033[92m'
COLOR_WARNING = '\033[93m'
COLOR_FAIL = '\033[91m'
COLOR_ENDC = '\033[0m'

class Package:

    def __init__(self):
        self.name = None
        self.version = None
        self.release = None

    def get_url(self):
        uri = MCLAZY_KOJI_INSTANCE
        uri += "%s/%s/%s/src/" % (self.name, self.version, self.release)
        uri += "%s-%s-%s.src.rpm" % (self.name, self.version, self.release)
        return uri

    def get_nvr(self):
        return "%s-%s-%s" % (self.name, self.version, self.release)

class Db:
    def __init__(self):
        self.con = sqlite3.connect(MCLAZY_COPR_DATABASE)
        cur = self.con.cursor()
        try:
            cur.execute("CREATE TABLE builds(timestamp INT, nvr TEXT)")
        except sqlite3.OperationalError:
            pass

    def __del__(self):
        self.con.close()

    def build_exists(self, pkg):
        cur = self.con.cursor()
        cur.execute("SELECT * FROM builds WHERE nvr = '%s'" % pkg.get_nvr())
        rows = cur.fetchall()
        return len(rows) > 0

    def add_build(self, pkg):
        if self.build_exists(pkg):
            return;
        cur = self.con.cursor()
        ts = int(time.time())
        cur.execute("INSERT INTO builds VALUES(%i,'%s')" % (ts, pkg.get_nvr()))

class Koji:
    def __init__(self):
        self.session = koji.ClientSession(MCLAZY_KOJI_HUB)

    def get_newest_build(self, pkgname):
        builds = self.session.getLatestRPMS(MCLAZY_BRANCH_INHERIT, package=pkgname, arch='src')
        latest = builds[0][0]
        pkg = Package()
        pkg.name = latest['name']
        pkg.version = latest['version']
        pkg.release = latest['release']
        return pkg

def main():

    # parse the configuration file
    pkg_names = []
    tree = ElementTree()
    tree.parse("./modules.xml")
    projects = list(tree.iter("project"))
    for project in projects:
        name = project.get('name')
        pkgname = project.get('pkgname')
        if not pkgname:
            pkgname = name;
        pkg_names.append(pkgname)

    koji = Koji()
    db = Db()

    for pkg_name in pkg_names:

        print COLOR_OKBLUE + "    INFO: Looking for " + pkg_name + COLOR_ENDC

        # get the latest build from koji
        pkg = koji.get_newest_build(pkg_name)
        print COLOR_OKBLUE + "    INFO: Latest version " + pkg.get_nvr() + COLOR_ENDC

        # has this build been submitted?
        if db.build_exists(pkg):
            print COLOR_OKBLUE + "    INFO: Already build in copr!" + COLOR_ENDC
            continue

        # submit to copr
        print COLOR_OKBLUE + "    INFO: Submitting URL " + pkg.get_url() + COLOR_ENDC
        rc = copr_cli.subcommands.build(MCLAZY_COPR_ID, [pkg.get_url()], None, None)
        if rc != True:
            print COLOR_FAIL + "    FAILED: build" + COLOR_ENDC
            break

        # add to database
        db.add_build(pkg)

if __name__ == "__main__":
    main()
