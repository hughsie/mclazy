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

import os
import subprocess
import urllib
import json
import re
import rpm
import argparse
import fnmatch
from xml.etree.ElementTree import ElementTree

from modules import ModulesXml

COLOR_HEADER = '\033[95m'
COLOR_OKBLUE = '\033[94m'
COLOR_OKGREEN = '\033[92m'
COLOR_WARNING = '\033[93m'
COLOR_FAIL = '\033[91m'
COLOR_ENDC = '\033[0m'

def run_command(cwd, argv):
    print("    INFO: running %s" % " ".join(argv))
    p = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, error = p.communicate()
    if p.returncode != 0:
        print(output)
        print(error)
    return p.returncode

def replace_spec_value(line, replace):
    if line.find(' ') != -1:
        return line.rsplit(' ', 1)[0] + ' ' + replace
    if line.find('\t') != -1:
        return line.rsplit('\t', 1)[0] + '\t' + replace
    return line

def unlock_file(lock_filename):
    if os.path.exists(lock_filename):
        os.unlink(lock_filename)

def get_modules(modules_file):
    """Read a list of modules we care about."""
    with open(modules_file,'r') as f:
        for line in f:
            if line.startswith('#'):
                continue
            yield line.strip()

def switch_branch_and_reset(pkg_cache, branch_name):
    rc = run_command (pkg_cache, ['git', 'clean', '-dfx'])
    if rc != 0:
        return rc
    rc = run_command (pkg_cache, ['git', 'reset', '--hard', 'HEAD'])
    if rc != 0:
        return rc
    rc = run_command (pkg_cache, ['git', 'checkout', branch_name])
    if rc != 0:
        return rc
    rc = run_command (pkg_cache, ['git', 'reset', '--hard', "origin/%s" % branch_name])
    if rc != 0:
        return rc

    return 0

def sync_to_master_branch(pkg_cache, args):
    rc = switch_branch_and_reset (pkg_cache, 'master')
    if rc != 0:
        print COLOR_FAIL + "    FAILED: switch to 'master' branch" + COLOR_ENDC
        return

    # First try a fast-forward merge
    rc = run_command (pkg_cache, ['git', 'merge', '--ff-only', args.fedora_branch])
    if rc != 0:
        print "    INFO: No fast-forward merge possible"
        # ... and if the ff merge fails, fall back to cherry-picking
        rc = run_command (pkg_cache, ['git', 'cherry-pick', args.fedora_branch])
        if rc != 0:
            run_command (pkg_cache, ['git', 'cherry-pick', '--abort'])
            print COLOR_FAIL + "    FAILED: cherry-pick" + COLOR_ENDC
            return

    rc = run_command (pkg_cache, ['git', 'push'])
    if rc != 0:
        print COLOR_FAIL + "    FAILED: push" + COLOR_ENDC
        return

    # Build the package
    rc = run_command (pkg_cache, ['fedpkg', 'build', '--nowait'])
    if rc != 0:
        print COLOR_FAIL + "    FAILED: build" + COLOR_ENDC
        return

# first two digits of version
def majorminor(ver):
    v = ver.split('.')
    return "%s.%s" % (v[0], v[1])

def main():

    # use the main mirror
    gnome_ftp = 'http://ftp.gnome.org/pub/GNOME/sources'
    lockfile = "mclazy.lock"

    # read defaults from command line arguments
    parser = argparse.ArgumentParser(description='Automatically build Fedora packages for a GNOME release')
    parser.add_argument('--fedora-branch', default="f20", help='The fedora release to target (default: f20)')
    parser.add_argument('--simulate', action='store_true', help='Do not commit any changes')
    parser.add_argument('--check-installed', action='store_true', help='Check installed version against built version')
    parser.add_argument('--relax-version-checks', action='store_true', help='Relax checks on the version numbering')
    parser.add_argument('--no-build', action='store_true', help='Do not actually build, e.g. for rawhide')
    parser.add_argument('--no-rawhide-sync', action='store_true', help='Do not push the same changes to git master branch')
    parser.add_argument('--cache', default="cache", help='The cache of checked out packages')
    parser.add_argument('--modules', default="modules.xml", help='The modules to search')
    parser.add_argument('--buildone', default=None, help='Only build one specific package')
    parser.add_argument('--buildroot', default=None, help='Use a custom buildroot, e.g. f18-gnome')
    parser.add_argument('--bump-soname', default=None, help='Build any package that deps on this')
    args = parser.parse_args()

    # use rpm to check the installed version
    installed_pkgs = {}
    if args.check_installed:
        print("    INFO: loading rpmdb")
        ts = rpm.TransactionSet()
        mi = ts.dbMatch()
        for h in mi:
            installed_pkgs[h['name']] = h['version']
        print("    INFO: loaded rpmdb with %i items" % len(installed_pkgs))

    # parse the configuration file
    modules = []
    data = ModulesXml(args.modules)
    print("Depsolving moduleset...")
    if not data.depsolve():
        print_fail("Failed to depsolve")
        return
    for item in data.items:
        if not item.name:
            continue
        if item.disabled:
            continue
        enabled = False

        # build just this
        if args.buildone == item.pkgname:
            enabled = True

        # build this as it deps on the thing that's just bumped the soname
        if args.bump_soname in item.deps:
            item.wait_repo = True
            enabled = True

        # build everything
        if args.buildone == None and args.bump_soname == None:
            enabled = True
        if enabled:
            modules.append((item.name, item.pkgname, item.release_glob, item.wait_repo))

    # create the cache directory if it's not already existing
    if not os.path.isdir(args.cache):
        os.mkdir(args.cache)

    # loop these
    for module, pkg, release_version, wait_repo in modules:
        print("%s:" % module)
        print("    INFO: package name: %s" % pkg)
        print("    INFO: version glob: %s" % release_version[args.fedora_branch])

        # ensure we've not locked this build in another instance
        lock_filename = args.cache + "/" + pkg + "-" + lockfile
        if os.path.exists(lock_filename):
            # check this process is still running
            is_still_running = False
            with open(lock_filename, 'r') as f:
                try:
                    pid = int(f.read())
                    if os.path.isdir("/proc/%i" % pid):
                        is_still_running = True
                except ValueError as e:
                    # pid in file was not an integer
                    pass

            if is_still_running:
                print("    INFO: ignoring as another process (PID %i) has this" % pid)
                continue
            else:
                print("    WARNING: process with PID %i locked but did not release" % pid)

        # create lockfile
        print("    INFO: creating lockfile")
        with open(lock_filename, 'w') as f:
            f.write("%s" % os.getpid())

        pkg_cache = os.path.join(args.cache, pkg)

        # ensure package is checked out
        if not os.path.isdir(args.cache + "/" + pkg):
            print("    INFO: git repo does not exist")
            rc = run_command(args.cache, ["fedpkg", "co", pkg])
            if rc != 0:
                print(COLOR_FAIL + "    FAILED: to checkout %s" % pkg + COLOR_ENDC)
                continue

        else:
            print("    INFO: git repo already exists")
            rc = run_command (pkg_cache, ['git', 'fetch'])
            if rc != 0:
                print(COLOR_FAIL + "    FAILED: to update repo %s" % pkg)
                continue

        if args.fedora_branch == 'rawhide':
            rc = switch_branch_and_reset (pkg_cache, 'master')
        else:
            rc = switch_branch_and_reset (pkg_cache, args.fedora_branch)

        if rc != 0:
            print(COLOR_FAIL + "    FAILED: switch branch" + COLOR_ENDC)
            continue

        # get the current version
        version = 0
        spec_filename = "%s/%s/%s.spec" % (args.cache, pkg, pkg)
        if not os.path.exists(spec_filename):
            print "    WARNING: No spec file"
            continue

        # open spec file
        try:
            spec = rpm.spec(spec_filename)
            version = spec.sourceHeader["version"]
        except ValueError as e:
            print "    WARNING: Can't parse spec file"
            continue
        print("    INFO: current version is %s" % version)

        # check for newer version on GNOME.org
        success = False
        for i in range (1, 20):
            try:
                urllib.urlretrieve ("%s/%s/cache.json" % (gnome_ftp, module), "%s/%s/cache.json" % (args.cache, pkg))
                success = True
                break
            except IOError as e:
                print "    WARNING: Failed to get JSON on try", i, e
        if not success:
            continue;

        new_version = None
        gnome_branch = release_version[args.fedora_branch]
        local_json_file = "%s/%s/cache.json" % (args.cache, pkg)
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
                print "    WARNING: Failed to read JSON at %s: %s" % (local_json_file, str(e))
                continue

            # find the newest version
            newest_remote_version = '0'
            for remote_ver in j[2][module]:
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
            print "    WARNING: no remote versions matching the gnome branch", gnome_branch
            print "    WARNING: check modules.xml is looking at the correct branch"
            continue

        print "    INFO: newest remote version is", newest_remote_version

        # is this newer than the rpm spec file version
        rc = rpm.labelCompare((None, newest_remote_version, None), (None, version, None))
        new_version = None
        if rc > 0:
            new_version = newest_remote_version

        # check the installed version
        if args.check_installed:
            if pkg in installed_pkgs:
                installed_ver = installed_pkgs[pkg]
                if installed_ver == newest_remote_version:
                    print "    INFO: installed version is up to date"
                else:
                    print "    INFO: installed version is", installed_ver
                    rc = rpm.labelCompare((None, installed_ver, None), (None, newest_remote_version, None))
                    if rc > 0:
                        print "    WARNING: installed version is newer than gnome branch version"
                        print "    WARNING: check modules.xml is looking at the correct branch"

        # nothing to do
        if new_version == None and not args.bump_soname:
            print("    INFO: No updates available")
            unlock_file(lock_filename)
            continue

        # never update a major version number */
        if new_version:
            if args.relax_version_checks:
                print("    INFO: Updating major version number, but ignoring")
            elif new_version.split('.')[0] != version.split('.')[0]:
                print("    WARNING: Cannot update major version numbers")
                continue

        # we need to update the package
        if new_version:
            print("    INFO: Need to update from %s to %s" %(version, new_version))

        # download the tarball if it doesn't exist
        if new_version:
            tarball = j[1][module][new_version]['tar.xz']
            dest_tarball = tarball.split('/')[1]
            if os.path.exists(pkg + "/" + dest_tarball):
                print("    INFO: source %s already exists" % dest_tarball)
            else:
                tarball_url = gnome_ftp + "/" + module + "/" + tarball
                print("    INFO: download %s" % tarball_url)
                if not args.simulate:
                    try:
                        urllib.urlretrieve (tarball_url, args.cache + "/" + pkg + "/" + dest_tarball)
                    except IOError as e:
                        print "    WARNING: Failed to get tarball", e
                        continue
                    # add the new source
                    run_command (pkg_cache, ['fedpkg', 'new-sources', dest_tarball])

        # prep the spec file for rpmdev-bumpspec
        if new_version:
            with open(spec_filename, 'r') as f:
                with open(spec_filename+".tmp", "w") as tmp_spec:
                    for line in f:
                        if line.startswith('Version:'):
                            line = replace_spec_value(line, new_version + '\n')
                        elif line.startswith('Release:'):
                            line = replace_spec_value(line, '0%{?dist}\n')
                        elif line.startswith(('Source:', 'Source0:')):
                            line = re.sub("/" + majorminor(version) + "/",
                                          "/" + majorminor(new_version) + "/",
                                          line)
                        tmp_spec.write(line)
            os.rename(spec_filename + ".tmp", spec_filename)

        # bump the spec file
        if args.bump_soname:
            comment = "Rebuilt for %s soname bump" % args.bump_soname
        else:
            comment = "Update to " + new_version
        cmd = ['rpmdev-bumpspec', "--comment=%s" % comment, "%s.spec" % pkg]
        run_command (pkg_cache, cmd)

        # run prep, and make sure patches still apply
        if not args.simulate:
            rc = run_command (pkg_cache, ['fedpkg', 'prep'])
            if rc != 0:
                print(COLOR_FAIL + "    FAILED: to build %s as patches did not apply" % pkg + COLOR_ENDC)
                continue

        # push the changes
        if args.simulate:
            print("    INFO: not pushing as simulating")
            continue

        # commit the changes
        rc = run_command (pkg_cache, ['git', 'commit', '-a', "--message=%s" % comment])
        if rc != 0:
            print(COLOR_FAIL + "    FAILED: commit" + COLOR_ENDC)
            continue
        rc = run_command (pkg_cache, ['git', 'push'])
        if rc != 0:
            print(COLOR_FAIL + "    FAILED: push" + COLOR_ENDC)
            continue

        # Try to push the same change to master branch
        if not args.no_rawhide_sync and args.fedora_branch != 'rawhide':
            sync_to_master_branch (pkg_cache, args)
            run_command (pkg_cache, ['git', 'checkout', args.fedora_branch])

        # work out release tag
        if args.fedora_branch == "f18":
            pkg_release_tag = 'fc18'
        elif args.fedora_branch == "f19":
            pkg_release_tag = 'fc19'
        elif args.fedora_branch == "f20":
            pkg_release_tag = 'fc20'
        elif args.fedora_branch == "rawhide":
            pkg_release_tag = 'fc21'
        else:
            print "    WARNING: Failed to get release tag for", args.fedora_branch
            continue;

        # build package
        if not args.no_build:
            if new_version:
                print(COLOR_OKBLUE + "    INFO: Building %s-%s-1.%s" % (pkg, new_version, pkg_release_tag) + COLOR_ENDC)
            else:
                print(COLOR_OKBLUE + "    INFO: Building %s-%s-1.%s" % (pkg, version, pkg_release_tag) + COLOR_ENDC)
            if args.buildroot:
                rc = run_command (pkg_cache, ['fedpkg', 'build', '--target', args.buildroot])
            else:
                rc = run_command (pkg_cache, ['fedpkg', 'build'])
            if rc != 0:
                print(COLOR_FAIL + "    FAILED: build" + COLOR_ENDC)
                continue

        # work out repo branch
        if args.fedora_branch == "f18":
            pkg_branch_name = 'f18-build'
        elif args.fedora_branch == "f19":
            pkg_branch_name = 'f19-build'
        elif args.fedora_branch == "f20":
            pkg_branch_name = 'f20-build'
        elif args.fedora_branch == "rawhide":
            pkg_branch_name = 'f21-build'
        else:
            print(COLOR_FAIL + "    WARNING: Failed to get repo branch tag for" + args.fedora_branch + COLOR_ENDC)
            continue;

        # wait for repo to sync
        if wait_repo and args.fedora_branch == "rawhide":
            rc = run_command (pkg_cache, ['koji', 'wait-repo', pkg_branch_name, '--build', "%s-%s-1.%s" % (pkg, new_version, pkg_release_tag)])
            if rc != 0:
                print(COLOR_FAIL + "    FAILED: wait for repo" + COLOR_ENDC)
                continue

        # success!
        print(COLOR_OKGREEN + "    SUCCESS: waited for build to complete" + COLOR_ENDC)

        # unlock build
        unlock_file(lock_filename)

if __name__ == "__main__":
    main()
