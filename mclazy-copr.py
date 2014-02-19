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
import argparse

import copr_cli.subcommands
from xml.etree.ElementTree import ElementTree

from modules import ModulesXml
from package import Package

COLOR_OKBLUE = '\033[94m'
COLOR_OKGREEN = '\033[92m'
COLOR_WARNING = '\033[93m'
COLOR_FAIL = '\033[91m'
COLOR_ENDC = '\033[0m'

class LocalDb:
    def __init__(self):
        self.con = sqlite3.connect('./copr.db')
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
        koji_instance = 'http://koji.fedoraproject.org/kojihub/'
        self.session = koji.ClientSession(koji_instance)

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

    # read defaults from command line arguments
    parser = argparse.ArgumentParser(description='Automatically build Fedora packages in COPR')
    parser.add_argument('--branch-source', default="rawhide", help='The branch to use as a source (default: rawhide)')
    parser.add_argument('--branch-destination', default="f20", help='The branch to use as a destination (default: f20)')
    parser.add_argument('--simulate', action='store_true', help='Do not commit any changes')
    parser.add_argument('--modules', default="modules.xml", help='The modules to search')
    parser.add_argument('--copr-id', default="f20-gnome-3-12", help='The COPR to use')
    parser.add_argument('--buildone', default=None, help='Only build one specific package')
    parser.add_argument('--bump-soname', default=None, help='Build this package any any that dep on it')
    parser.add_argument('--ignore-existing', action='store_true', help='Build the module even if it already exists in COPR')
    parser.add_argument('--ignore-version', action='store_true', help='Build the module even if the same version exists in the destination')
    args = parser.parse_args()

    # parse the configuration file
    data = ModulesXml(args.modules)

    koji = Koji()
    db = LocalDb()

    current_depsolve_level = 0;
    builds_in_progress = []

    # only build one module
    if args.buildone:
        for item in data.items:
            if item.pkgname == args.buildone:
                item.disabled = False
            else:
                item.disabled = True
    else:
        print("Depsolving moduleset...")
        if not data.depsolve():
            print_fail("Failed to depsolve")
            return

    # build one module, plus the things that depend on it
    if args.bump_soname:
        args.ignore_existing = True
        for item in data.items:
            disabled = True
            if item.pkgname == args.bump_soname:
                disabled = False
            else:
                for dep in item.deps:
                    if dep == args.bump_soname:
                        disabled = False
                        break
            item.disabled = disabled

    for item in data.items:

        # wait for builds
        if current_depsolve_level != item._depsolve_order:
            if len(builds_in_progress):
                print("Waiting for depsolve level %i" % current_depsolve_level)
                rc = wait_for_builds(builds_in_progress, db)
                if not rc:
                    print_fail("Aborting")
                    break
            current_depsolve_level = item._depsolve_order
            print("Now running depsolve level %i" % current_depsolve_level)

        # skip
        if item.disabled:
            continue

        # get the latest build from koji
        pkg = koji.get_newest_build(args.branch_source, item.pkgname)
        if not pkg:
            print_fail("package %s does not exists in %s" % (item.pkgname, args.branch_destination))
            continue
        print("Latest version of %s in %s: %s" % (item.pkgname, args.branch_source, pkg.get_nvr()))

        # has this build been submitted?
        if not args.ignore_existing and db.build_exists(pkg):
            print("Already built in copr")
            continue

        # does this version already exist?
        pkg_stable = koji.get_newest_build(args.branch_destination, item.pkgname)
        if pkg_stable:
            print("Latest version in %s: %s" % (args.branch_destination, pkg_stable.get_nvr()))
            if not args.ignore_version and pkg.version == pkg_stable.version:
                print("Already exists same version")
                continue

        # submit to copr
        print("Submitting URL " + pkg.get_url())
        if args.simulate:
            continue
        pkg.build_id = build_in_copr(args.copr_id, [pkg.get_url()])
        if not pkg.build_id:
            print_fail("build")
            break
        print("Adding build " + str(pkg.build_id))
        builds_in_progress.append(pkg)

    # final pass
    if len(builds_in_progress):
        rc = wait_for_builds(builds_in_progress, db)
        if not rc:
            print_fail("Failed")

    print_info("Done!")

if __name__ == "__main__":
    main()
