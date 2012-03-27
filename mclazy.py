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
import rpm
import argparse

def run_command(cwd, argv):
    print("    INFO: running %s" % " ".join(argv))
    p = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    p.wait()
    if p.returncode != 0:
        print(p.stdout.read())
        print(p.stderr.read())
    return p.returncode;

def replace_spec_value(line, replace):
    if line.find(' ') != -1:
        return line.rsplit(' ', 1)[0] + ' ' + replace
    if line.find('\t') != -1:
        return line.rsplit('\t', 1)[0] + '\t' + replace
    return line

def unlock_file(lock_filename):
    if os.path.exists(lock_filename):
        os.unlink(lock_filename)

def main():

    # use the main mirror
    gnome_ftp = 'http://ftp.gnome.org/pub/GNOME/sources'
    lockfile = "mclazy.lock"

    # read defaults from command line arguments
    parser = argparse.ArgumentParser(description='Automatically build Fedora packages for a GNOME release')
    parser.add_argument('--fedora-branch', default="f17", help='The fedora release to target (default: f17)')
    parser.add_argument('--gnome-branch', default="3.4", help='The GNOME release to target (default: 3.4)')
    parser.add_argument('--simulate', action='store_true', help='Do not commit any changes')
    parser.add_argument('--no-build', action='store_true', help='Do not actually build, e.g. for rawhide')
    parser.add_argument('--cache', default="cache", help='The cache of checked out packages')
    parser.add_argument('--packages', default="packages.txt", help='The module to package mapping filename')
    parser.add_argument('--modules', default="modules.txt", help='The modules to search')
    args = parser.parse_args()

    # read a list of modules we care about
    modules = []
    with open(args.modules,'r') as f:
        for line in f:
            if line.startswith('#'):
                continue
            modules.append(line.strip())

    # read a list of module -> package names
    package_map = {}
    with open(args.packages,'r') as f:
        for line in f:
            if line.startswith('#'):
                continue
            line = line.split()
            package_map[line[0]] = line[1]

    # create the cache directory if it's not already existing
    if not os.path.isdir(args.cache):
        os.mkdir(args.cache)

    # loop these
    for module in modules:

        print("%s:" % module)
        if not module in package_map:
            pkg = module
        else:
            pkg = package_map[module]
            print("    INFO: package name override to %s" % pkg)

        # ensure we've not locked this build in another instance
        lock_filename = args.cache + "/" + pkg + "-" + lockfile
        if os.path.exists(lock_filename):
            # check this process is still running
            is_still_running = False
            with open(lock_filename, 'r') as f:
                pid_str = f.read()
                pid = 0
                if len(pid_str) > 0:
                    pid = int(pid_str)
                if os.path.isdir("/proc/%i" % pid):
                    is_still_running = True
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
                print("    FAILED: to checkout %s" % pkg)
                continue

        else:
            print("    INFO: git repo already exists")
            run_command (pkg_cache, ['git', 'clean', '-dfx'])
            run_command (pkg_cache, ['git', 'reset', '--hard'])
            run_command (pkg_cache, ['git', 'pull'])

        run_command (pkg_cache, ['git', 'checkout', args.fedora_branch])

        # get the current version
        version = 0
        spec_filename = "%s/%s/%s.spec" % (args.cache, pkg, pkg)
        if not os.path.exists(spec_filename):
            print "    WARNING: No spec file"
            continue

        spec = rpm.spec(spec_filename)
        version = spec.sourceHeader["version"]
        print("    INFO: current version is %s" % version)

        # check for newer version on GNOME.org
        urllib.urlretrieve ("%s/%s/cache.json" % (gnome_ftp, module), "%s/%s/cache.json" % (args.cache, pkg))
        new_version = None
        with open("%s/%s/cache.json" % (args.cache, pkg), 'r') as f:

            # the format of the json file is as follows:
            # j[0] = some kind of version number?
            # j[1] = the files keyed for each release, e.g.
            #        { 'pkgname' : {'2.91.1' : {u'tar.gz': u'2.91/gpm-2.91.1.tar.gz'} } }
            # j[2] = array of remote versions, e.g.
            #        { 'pkgname' : {  '3.3.92', '3.4.0' }
            # j[3] = the LATEST-IS files
            j = json.loads(f.read())

            # find any newer version
            for remote_ver in j[2][module]:
                if not remote_ver.startswith(args.gnome_branch):
                    continue;
                rc = rpm.labelCompare((None, remote_ver, None), (None, version, None))
                if rc > 0:
                    new_version = remote_ver

        # nothing to do
        if new_version == None:
            print("    INFO: No updates available")
            unlock_file(lock_filename)
            continue

        # not a gnome release number */
        if not new_version.startswith('3.4.'):
            print("    WARNING: Not gnome release numbering")
            continue

        # never update a major version number */
        if new_version.split('.')[0] != version.split('.')[0]:
            print("    WARNING: Cannot update major version numbers")
            continue

        # we need to update the package
        print("    INFO: Need to update from %s to %s" %(version, new_version))

        # download the tarball if it doesn't exist
        tarball = j[1][module][new_version]['tar.xz']
        dest_tarball = tarball.split('/')[1]
        if os.path.exists(pkg + "/" + dest_tarball):
            print("    INFO: source %s already exists" % dest_tarball)
        else:
            tarball_url = gnome_ftp + "/" + module + "/" + tarball
            print("    INFO: download %s" % tarball_url)
            if not args.simulate:
                urllib.urlretrieve (tarball_url, args.cache + "/" + pkg + "/" + dest_tarball)
                # add the new source
                run_command (pkg_cache, ['fedpkg', 'new-sources', dest_tarball])

        # prep the spec file for rpmdev-bumpspec
        new_spec_lines = []
        with open(spec_filename, 'r') as f:
            with open(spec_filename+".tmp", "w") as tmp_spec:
                for line in f:
                    if line.startswith('Version:'):
                        line = replace_spec_value(line, new_version + '\n')
                    elif line.startswith('Release:'):
                        line = replace_spec_value(line, '0%{?dist}\n')
                    tmp_spec.write(line)
        os.rename(spec_filename+".tmp", spec_filename)

        # bump the spec file
        comment = "Update to " + new_version
        cmd = ['rpmdev-bumpspec', "--comment=%s" % comment, "%s.spec" % pkg]
        run_command (pkg_cache, cmd)

        # run prep, and make sure patches still apply
        if not args.simulate:
            rc = run_command (pkg_cache, ['fedpkg', 'prep'])
            if rc != 0:
                print("    FAILED: to build %s as patches did not apply" % pkg)
                continue

        # commit and push changelog
        if args.simulate:
            print("    INFO: not pushing as simulating")
            continue
        rc = run_command (pkg_cache, ['fedpkg', 'commit', "-m %s" % comment, '-p'])
        if rc != 0:
            print("    FAILED: push")
            continue

        # build package
        if not args.no_build:
            print("    INFO: Building %s-%s-1.fc17" % (pkg, new_version))
            rc = run_command (pkg_cache, ['fedpkg', 'build'])
            if rc != 0:
                print("    FAILED: build")
                continue

        # success!
        print("    SUCCESS: waiting for build to complete")

        # unlock build
        unlock_file(lock_filename)

if __name__ == "__main__":
    main()
