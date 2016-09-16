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

# Copyright (C) 2012
#    Richard Hughes <richard@hughsie.com>

""" A simple script that builds GNOME packages for koji """

import os
import subprocess
import urllib
import json
import re
import rpm
import argparse
import fnmatch
import glob

# internal
from modules import ModulesXml
from package import Package
from log import print_debug, print_info, print_fail
#from copr_helper import CoprHelper, CoprBuildStatus, CoprException

def replace_spec_value(line, replace):
    if line.find(' ') != -1:
        return line.rsplit(' ', 1)[0] + ' ' + replace
    if line.find('\t') != -1:
        return line.rsplit('\t', 1)[0] + '\t' + replace
    return line

# first two digits of version
def majorminor(ver):
    v = ver.split('.')
    return "%s.%s" % (v[0], v[1])

def main():

    # use the main mirror
    gnome_ftp = 'http://ftp.gnome.org/pub/GNOME/sources'

    # read defaults from command line arguments
    parser = argparse.ArgumentParser(description='Automatically build Fedora packages for a GNOME release')
    parser.add_argument('--fedora-branch', default="rawhide", help='The fedora release to target (default: rawhide)')
    parser.add_argument('--simulate', action='store_true', help='Do not commit any changes')
    parser.add_argument('--check-installed', action='store_true', help='Check installed version against built version')
    parser.add_argument('--force-build', action='store_true', help='Always build even when not newer')
    parser.add_argument('--relax-version-checks', action='store_true', help='Relax checks on the version numbering')
    parser.add_argument('--cache', default="cache", help='The cache of checked out packages')
    parser.add_argument('--buildone', default=None, help='Only build one specific package')
    parser.add_argument('--buildroot', default=None, help='Use a custom buildroot, e.g. f18-gnome')
    parser.add_argument('--bump-soname', default=None, help='Build any package that deps on this')
    parser.add_argument('--copr-id', default=None, help='The COPR to optionally use')
    args = parser.parse_args()

    if args.copr_id:
        copr = CoprHelper(args.copr_id)

    # create the cache directory if it's not already existing
    if not os.path.isdir(args.cache):
        os.mkdir(args.cache)

    # use rpm to check the installed version
    installed_pkgs = {}
    if args.check_installed:
        print_info("Loading rpmdb")
        ts = rpm.TransactionSet()
        mi = ts.dbMatch()
        for h in mi:
            installed_pkgs[h['name']] = h['version']
        print_debug("Loaded rpmdb with %i items" % len(installed_pkgs))

    # parse the configuration file
    modules = []
    data = ModulesXml('modules.xml')
    if not args.buildone:
        print_debug("Depsolving moduleset...")
        if not data.depsolve():
            print_fail("Failed to depsolve")
            return
    for item in data.items:

        # ignore just this one module
        if item.disabled:
            continue

        # build just one module
        if args.buildone:
            if args.buildone != item.name:
                continue

        # just things that have this as a dep
        if args.bump_soname:
            if args.bump_soname not in item.deps:
                continue

        # things we can't autobuild as we don't have upstream data files
        if not item.ftpadmin:
            continue

        # things that are obsolete in later versions
        if args.copr_id:
            if not args.copr_id[10:] in item.branches:
                continue

        # get started
        print_info("Loading %s" % item.name)
        if item.pkgname != item.name:
            print_debug("Package name: %s" % item.pkgname)
        print_debug("Version glob: %s" % item.release_glob[args.fedora_branch])

        # ensure package is checked out
        if not item.setup_pkgdir(args.cache, args.fedora_branch):
            continue

        # get the current version from the spec file
        if not item.parse_spec():
            continue

        print_debug("Current version is %s" % item.version)

        # check for newer version on GNOME.org
        success = False
        for i in range (1, 20):
            try:
                urllib.urlretrieve ("%s/%s/cache.json" % (gnome_ftp, item.name), "%s/%s/cache.json" % (args.cache, item.pkgname))
                success = True
                break
            except IOError as e:
                print_fail("Failed to get JSON on try %i: %s" % (i, e))
        if not success:
            continue

        new_version = None
        gnome_branch = item.release_glob[args.fedora_branch]
        local_json_file = "%s/%s/cache.json" % (args.cache, item.pkgname)
        with open(local_json_file, 'r') as f:

            # the format of the json file is as follows:
            # j[0] = some kind of version number?
            # j[1] = the files keyed for each release, e.g.
            #        { 'pkgname' : {'2.91.1' : {u'tar.gz': u'2.91/gpm-2.91.1.tar.gz'} } }
            # j[2] = array of remote versions, e.g.
            #        { 'pkgname' : {  '3.3.92', '3.4.0' }
            # j[3] = the LATEST-IS files
            try:
                j = json.loads(f.read())
            except Exception, e:
                print_fail("Failed to read JSON at %s: %s" % (local_json_file, str(e)))
                continue

            # find the newest version
            newest_remote_version = '0'
            for remote_ver in j[2][item.name]:
                version_valid = False
                for b in gnome_branch.split(','):
                    if fnmatch.fnmatch(remote_ver, b):
                        version_valid = True
                        break
                if not args.relax_version_checks and not version_valid:
                    continue
                rc = rpm.labelCompare((None, remote_ver, None), (None, newest_remote_version, None))
                if rc > 0:
                    newest_remote_version = remote_ver
        if newest_remote_version == '0':
            print_fail("No remote versions matching the gnome branch %s" % gnome_branch)
            print_fail("Check modules.xml is looking at the correct branch")
            continue

        print_debug("Newest remote version is: %s" % newest_remote_version)

        # is this newer than the rpm spec file version
        rc = rpm.labelCompare((None, newest_remote_version, None), (None, item.version, None))
        new_version = None
        if rc > 0:
            new_version = newest_remote_version

        # check the installed version
        if args.check_installed:
            if item.pkgname in installed_pkgs:
                installed_ver = installed_pkgs[item.pkgname]
                if installed_ver == newest_remote_version:
                    print_debug("installed version is up to date")
                else:
                    print_debug("installed version is", installed_ver)
                    rc = rpm.labelCompare((None, installed_ver, None), (None, newest_remote_version, None))
                    if rc > 0:
                        print_fail("installed version is newer than gnome branch version")
                        print_fail("check modules.xml is looking at the correct branch")

        # nothing to do
        if new_version == None and not args.bump_soname and not args.force_build:
            print_debug("No updates available")
            continue

        # never update a major version number */
        if new_version:
            if args.relax_version_checks:
                print_debug("Updating major version number, but ignoring")
            elif new_version.split('.')[0] != item.version.split('.')[0]:
                print_fail("Cannot update major version numbers")
                continue

        # we need to update the package
        if new_version:
            print_debug("Need to update from %s to %s" %(item.version, new_version))

        # download the tarball if it doesn't exist
        if new_version:
            tarball = j[1][item.name][new_version]['tar.xz']
            dest_tarball = tarball.split('/')[1]
            if os.path.exists(item.pkgname + "/" + dest_tarball):
                print_debug("Source %s already exists" % dest_tarball)
            else:
                tarball_url = gnome_ftp + "/" + item.name + "/" + tarball
                print_debug("Download %s" % tarball_url)
                if not args.simulate:
                    try:
                        urllib.urlretrieve (tarball_url, args.cache + "/" + item.pkgname + "/" + dest_tarball)
                    except IOError as e:
                        print_fail("Failed to get tarball: %s" % e)
                        continue

                    # add the new source
                    item.new_tarball(dest_tarball)

        # prep the spec file for rpmdev-bumpspec
        if new_version:
            with open(item.spec_filename, 'r') as f:
                with open(item.spec_filename+".tmp", "w") as tmp_spec:
                    for line in f:
                        if line.startswith('Version:'):
                            line = replace_spec_value(line, new_version + '\n')
                        elif line.startswith('Release:'):
                            line = replace_spec_value(line, '0%{?dist}\n')
                        elif line.startswith(('Source:', 'Source0:')):
                            line = re.sub("/" + majorminor(item.version) + "/",
                                          "/" + majorminor(new_version) + "/",
                                          line)
                        tmp_spec.write(line)
            os.rename(item.spec_filename + ".tmp", item.spec_filename)

        # bump the spec file
        comment = None
        if args.bump_soname:
            comment = "Rebuilt for %s soname bump" % args.bump_soname
        elif new_version:
            comment = "Update to " + new_version
        if comment:
            cmd = ['rpmdev-bumpspec', "--comment=%s" % comment, "%s.spec" % item.pkgname]
            item.run_command(cmd)

        # run prep, and make sure patches still apply
        if not args.simulate:
            if not item.check_patches():
                print_fail("to build %s as patches did not apply" % item.pkgname)
                continue

        # push the changes
        if args.simulate:
            print_debug("Not pushing as simulating")
            continue

        # commit the changes
        if comment and not item.commit_and_push(comment):
            print_fail("push")
            continue

        # COPR, so build srpm, upload and build
        if item.is_copr:
            if not item.run_command(['fedpkg', "--dist=%s" % item.dist, 'srpm']):
                print_fail("to build srpm")
                continue

            # extract the nevr from the package
            new_srpm = glob.glob(args.cache + "/" + item.pkgname + '/*.src.rpm')[0]
            pkg = Package(new_srpm)

            # check if it already exists
            status = copr.get_pkg_status(pkg)
            if status == CoprBuildStatus.ALREADY_BUILT:
                print_debug ("Already built in COPR")
                continue
            elif status == CoprBuildStatus.IN_PROGRESS:
                print_debug ("Already building in COPR")
                continue

            # upload the package somewhere shared
            if os.getenv('USERNAME') == 'hughsie':
                upload_dir = 'rhughes@fedorapeople.org:/home/fedora/rhughes/public_html/copr/'
                upload_url = 'http://rhughes.fedorapeople.org/copr/'
            elif os.getenv('USERNAME') == 'kalev':
                upload_dir = 'kalev@fedorapeople.org:/home/fedora/kalev/public_html/copr/'
                upload_url = 'http://kalev.fedorapeople.org/copr/'
            else:
                print_fail ("USERNAME not valid, ping hughsie on irc")
                continue

            print_debug("Uploading local package to " + upload_dir)
            p = subprocess.Popen(['scp', '-q', new_srpm, upload_dir])
            p.wait()
            pkg.url = upload_url + os.path.basename(new_srpm)

            if not copr.build(pkg):
                print_fail("COPR build")
                break
            rc = copr.wait_for_builds()
            if not rc:
                print_fail("waiting")
            continue

        # work out release tag
        elif args.fedora_branch == "f23":
            pkg_release_tag = 'fc23'
        elif args.fedora_branch == "f24":
            pkg_release_tag = 'fc24'
        elif args.fedora_branch == "f25":
            pkg_release_tag = 'fc25'
        elif args.fedora_branch == "rawhide":
            pkg_release_tag = 'fc26'
        else:
            print_fail("Failed to get release tag for %s" % args.fedora_branch)
            continue

        # build package
        if new_version:
            print_info("Building %s-%s-1.%s" % (item.pkgname, new_version, pkg_release_tag))
        else:
            print_info("Building %s-%s-1.%s" % (item.pkgname, item.version, pkg_release_tag))
        if args.buildroot:
            rc = item.run_command(['fedpkg', 'build', '--target', args.buildroot])
        else:
            rc = item.run_command(['fedpkg', 'build'])
        if not rc:
            print_fail("Build")
            continue

        # work out repo branch
        elif args.fedora_branch == "f23":
            pkg_branch_name = 'f23-build'
        elif args.fedora_branch == "f24":
            pkg_branch_name = 'f24-build'
        elif args.fedora_branch == "f25":
            pkg_branch_name = 'f25-build'
        elif args.fedora_branch == "rawhide":
            pkg_branch_name = 'f26-build'
        else:
            print_fail("Failed to get repo branch tag for" + args.fedora_branch)
            continue

        # wait for repo to sync
        if item.wait_repo and args.fedora_branch == "rawhide":
            rc = item.run_command(['koji', 'wait-repo', pkg_branch_name, '--build', "%s-%s-1.%s" % (item.pkgname, new_version, pkg_release_tag)])
            if not rc:
                print_fail("Wait for repo")
                continue

if __name__ == "__main__":
    main()
