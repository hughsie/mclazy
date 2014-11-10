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

import os
import sys
import rpm
import argparse

from log import print_debug, print_info, print_fail
from copr_helper import CoprHelper, CoprBuildStatus, CoprException
from koji_helper import KojiHelper
from package import Package
from modules import ModulesXml

def main():

    parser = argparse.ArgumentParser(description='Build a list of packages')
    parser.add_argument('--branch-source', default="f21", help='The branch to use as a source')
    parser.add_argument('--copr-id', default="el7-gnome-3-14", help='The COPR to use')
    parser.add_argument('--packages', default="./data/el7-gnome-3-14.txt", help='the list if packages to build')
    args = parser.parse_args()

    copr = CoprHelper(args.copr_id)
    koji = KojiHelper()

    data = ModulesXml('modules.xml')

    # add the copr id (e.g. el7) to any items in modules.xml file
    f = open(args.packages, 'r')
    for l in f.readlines():
        if l.startswith('#'):
            continue
        if l.startswith('\n'):
            continue
        linedata = l.strip().split(',')
        pkgname = linedata[0]
        item = data._get_item_by_pkgname(pkgname)
        if not item:
            print("%s not found" % pkgname)
            continue
        item.releases.append(copr.release)
        item.custom_package_url = None
        if len(linedata) > 1:
            item.custom_package_url = linedata[1]
    f.close()

    # disable any modules without the copr-specific release
    for item in data.items:
        if copr.release not in item.releases:
            item.disabled = True
            continue

    # depsolve
    print_debug("Depsolving moduleset...")
    if not data.depsolve():
        print_fail("Failed to depsolve")
        return

    # process all packages
    current_depsolve_level = 0
    for item in data.items:
        if item.disabled:
            continue;

        # wait for builds
        if current_depsolve_level != item.depsolve_level:
            rc = copr.wait_for_builds()
            if not rc:
                print_fail("A build failed, so aborting")
                break
            current_depsolve_level = item.depsolve_level
            print_debug("Now running depsolve level %i" % current_depsolve_level)

        # find the koji package
        pkg = None
        if not item.custom_package_url:
            pkg = koji.get_newest_build(args.branch_source, item.pkgname)
            if not pkg:
                print_fail("package %s does not exists in koji" % item.pkgname)
                continue
            pkg2 = koji.get_newest_build(args.branch_source + '-updates-candidate', item.pkgname)
            if not pkg2:
                print_fail("package %s does not exists in koji" % item.pkgname)
                continue

            # use the newest package
            if pkg.get_nvr() != pkg2.get_nvr():
                if rpm.labelCompare(pkg.get_evr(), pkg2.get_evr()) < 0:
                    pkg = pkg2;
        else:
            pkg = Package()
            nvr = os.path.basename(item.custom_package_url).rsplit('-', 2)
            pkg.name = nvr[0]
            pkg.version = nvr[1]
            pkg.release = nvr[2].replace('.src.rpm', '')
            pkg.url = item.custom_package_url
            
        print_debug("Latest version of %s: %s" % (item.pkgname, pkg.get_nvr()))

        # find if the package has been built in the copr
        try:
            status = copr.get_pkg_status(pkg)
        except CoprException, e:
            print_fail(str(e))
            continue
        if status == CoprBuildStatus.ALREADY_BUILT:
            print_debug("Already built")
            continue
        elif status == CoprBuildStatus.FAILED_TO_BUILD:
            print_debug("Failed, so retrying build")
        elif status == CoprBuildStatus.NOT_FOUND:
            print_debug("Not found, so building")
        elif status == CoprBuildStatus.IN_PROGRESS:
            print_debug("Already in progress")
            continue
        else:
            print_fail("copr status unknown: %s" % status)
            continue

        # submit build and wait for it to complete
        if not copr.build(pkg):
            print_fail("Failed to submit build")
            break

    # final pass
    rc = copr.wait_for_builds()
    if not rc:
        print_fail("Failed")

    print_info("Done!")

if __name__ == "__main__":
    main()
