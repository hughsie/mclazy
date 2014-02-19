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

""" A simple script that builds GNOME packages for COPR """

import argparse

# internal
from log import print_debug, print_info, print_fail
from modules import ModulesXml
from koji_helper import KojiHelper
from copr_helper import CoprHelper

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

    koji = KojiHelper()
    copr = CoprHelper(args.copr_id)

    current_depsolve_level = 0

    # only build one module
    if args.buildone:
        for item in data.items:
            if item.pkgname in args.buildone.split(','):
                item.disabled = False
            else:
                item.disabled = True
    else:
        print_info("Depsolving moduleset")
        if not data.depsolve():
            print_fail("Failed to depsolve")
            return

    # build one module, plus the things that depend on it
    if args.bump_soname:
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
        if current_depsolve_level != item.depsolve_level:
            rc = copr.wait_for_builds()
            if not rc:
                print_fail("A build failed, so aborting")
                break
            current_depsolve_level = item.depsolve_level
            print_debug("Now running depsolve level %i" % current_depsolve_level)

        # skip
        if item.disabled:
            continue

        # get the latest build from koji
        pkg = koji.get_newest_build(args.branch_source, item.pkgname)
        if not pkg:
            print_fail("package %s does not exists in %s" % (item.pkgname, args.branch_destination))
            continue
        print_debug("Latest version of %s in %s: %s" % (item.pkgname, args.branch_source, pkg.get_nvr()))

        # has this build been submitted?
        if copr.build_exists(pkg):
            if not args.ignore_existing and not args.bump_soname:
                print_debug("Already built in copr")
                continue
        else:
            if args.bump_soname and args.bump_soname != item.pkgname:
                print_debug("Not building %s as not yet built in copr" % item.pkgname)
                continue

        # does this version already exist?
        pkg_stable = koji.get_newest_build(args.branch_destination, item.pkgname)
        if pkg_stable:
            print_debug("Latest version in %s: %s" % (args.branch_destination, pkg_stable.get_nvr()))
            if not args.ignore_version and pkg.version == pkg_stable.version:
                print_debug("Already exists same version")
                continue

        # submit to copr
        print_debug("Submitting URL " + pkg.get_url())
        if args.simulate:
            continue
        if not copr.build(pkg):
            print_fail("build")
            break

    # final pass
    rc = copr.wait_for_builds()
    if not rc:
        print_fail("Failed")

    print_info("Done!")

if __name__ == "__main__":
    main()
