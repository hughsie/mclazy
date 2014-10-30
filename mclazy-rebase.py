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
import argparse

from log import print_debug, print_info, print_fail
from copr_helper import CoprHelper, CoprBuildStatus, CoprException
from koji_helper import KojiHelper
from package import Package

def main():

    parser = argparse.ArgumentParser(description='Build a list of packages')
    parser.add_argument('--branch-source', default="f21", help='The branch to use as a source')
    parser.add_argument('--copr-id', default="el7-gnome-3-14-minimal", help='The COPR to use')
    parser.add_argument('--packages', default="./el7-gnome-3-14.txt", help='the list if packages to build')
    args = parser.parse_args()

    copr = CoprHelper(args.copr_id)
    koji = KojiHelper()

    f = open(args.packages, 'r')
    for l in f.readlines():
        if l.startswith('#'):
            continue
        if l.startswith('\n'):
            continue
        data = l.strip().split(',')
        pkgname = data[0]
        if pkgname == 'exit':
            break
        if len(data) == 1:
            custom_package_url = None
        else:
            custom_package_url = data[1]

        # find the f21 package
        if not custom_package_url:
            pkg = koji.get_newest_build(args.branch_source, pkgname)
            if not pkg:
                print_fail("package %s does not exists in koji" % pkgname)
                continue
        else:
            pkg = Package()
            nvr = os.path.basename(custom_package_url).rsplit('-', 2)
            pkg.name = nvr[0]
            pkg.version = nvr[1]
            pkg.release = nvr[2].replace('.src.rpm', '')
            pkg.url = custom_package_url
            
        print_debug("Latest version of %s: %s" % (pkgname, pkg.get_nvr()))

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
        rc = copr.wait_for_builds()
        if not rc:
            print_fail("Failed to build package")
            break
    f.close()

if __name__ == "__main__":
    main()
