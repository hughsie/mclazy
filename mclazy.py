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
import string
import argparse

def run_command(cache, pkg, argv):
    print "    INFO: running", string.join(argv, " ")
    if not pkg:
        directory = cache
    else:
        directory = cache + "/" + pkg
    p = subprocess.Popen(argv, cwd=directory, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    p.wait()
    if p.returncode != 0:
        print p.stdout.read()
        print p.stderr.read()
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
    f = open(args.modules,'r')
    for line in f.readlines():
        if line.startswith('#'):
            continue
        modules.append(line.replace('\n',''))
    f.close()

    # read a list of module -> package names
    package_map = {}
    f = open(args.packages,'r')
    for line in f.readlines():
        if line.startswith('#'):
            continue
        package_map[line.split()[0]] = line.split()[1]
    f.close()

    # create the cache directory if it's not already existing
    if not os.path.isdir(args.cache):
        os.mkdir(args.cache)

    # loop these
    for module in modules:

        print module, ":"
        if not module in package_map:
            pkg = module
        else:
            pkg = package_map[module]
            print "    INFO: package name override to", pkg

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
            f.closed
            if is_still_running:
                print "    INFO: ignoring as another process (PID %i) has this" % pid
                continue
            else:
                print "    WARNING: process with PID %i locked but did not release" % pid

        # create lockfile
        print "    INFO: creating lockfile"
        with open(lock_filename, 'w') as f:
            f.write("%s" % os.getpid())
        f.closed

        # ensure package is checked out
        newly_created = False
        if os.path.isdir(args.cache + "/" + pkg):
            print "    INFO: git repo already exists"
        else:
            print "    INFO: git repo does not exist"
            rc = run_command(args.cache, None, ["fedpkg", "co", pkg])
            if rc != 0:
                print "    FAILED: to checkout %s", pkg
                continue
            newly_created = True

        # switch to the correct branch and setup so it's good to use
        if not newly_created:
            rc = run_command (args.cache, pkg, ['git', 'clean', '-dfx'])
            rc = run_command (args.cache, pkg, ['git', 'reset', '--hard'])
            #rc = run_command (args.cache, pkg, ['git', 'pull'])
        rc = run_command (args.cache, pkg, ['git', 'checkout', args.fedora_branch])

        # get the current version
        version = 0
        spec_lines = []
        spec_filename = "%s/%s/%s.spec" % (args.cache, pkg, pkg)
        if not os.path.exists(spec_filename):
            print "    WARNING: No spec file"
            continue

        with open(spec_filename, 'r') as f:
            spec_lines = f.readlines()
            for line in spec_lines:
                if line.startswith('Version:'):
                    version = line.split()[1]
        f.closed
        if version.find('%') != -1:
            print "    WARNING: Cannot autobump as version conditionals present:", version
            continue
        print "    INFO: current version is", version

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
        f.closed

        # nothing to do
        if new_version == None:
            print "    INFO: No updates available"
            unlock_file(lock_filename)
            continue

        # not a gnome release number */
        if not new_version.startswith('3.4.'):
            print "    WARNING: Not gnome release numbering"
            continue

        # never update a major version number */
        if new_version.split('.')[0] != version.split('.')[0]:
            print "    WARNING: Cannot update major version numbers"
            continue

        # we need to update the package
        print "    INFO: Need to update from", version, "to", new_version

        # download the tarball if it doesn't exist
        tarball = j[1][module][new_version]['tar.xz']
        dest_tarball = tarball.split('/')[1]
        if os.path.exists(pkg + "/" + dest_tarball):
            print "    INFO: source", dest_tarball, "already exists"
        else:
            tarball_url = gnome_ftp + "/" + module + "/" + tarball
            print "    INFO: download", tarball_url
            if not args.simulate:
                urllib.urlretrieve (tarball_url, args.cache + "/" + pkg + "/" + dest_tarball)
                # add the new source
                rc = run_command (args.cache, pkg, ['fedpkg', 'new-sources', dest_tarball])

        # prep the spec file for rpmdev-bumpspec
        new_spec_lines = []
        for line in spec_lines:
            if line.startswith('Version:'):
                line = replace_spec_value(line, new_version + '\n');
            elif line.startswith('Release:'):
                line = replace_spec_value(line, '0%{?dist}\n');
            new_spec_lines.append(line)
        with open(spec_filename, 'w') as f:
            f.writelines(new_spec_lines)
        f.closed

        # bump the spec file
        comment = "Update to " + new_version
        cmd = ['rpmdev-bumpspec', "--comment=%s" % comment, "%s.spec" % pkg]
        rc = run_command (args.cache, pkg, cmd)

        # run prep, and make sure patches still apply
        if not args.simulate:
            rc = run_command (args.cache, pkg, ['fedpkg', 'prep'])
            if rc != 0:
                print "    FAILED: to build", pkg, "as patches did not apply"
                continue

        # commit and push changelog
        if args.simulate:
            print "    INFO: not pushing as simulating"
            continue
        rc = run_command (args.cache, pkg, ['fedpkg', 'commit', "-m %s" % comment, '-p'])
        if rc != 0:
            print "    FAILED: push"
            continue

        # build package
        if not args.no_build:
            print "    INFO: Building %s-%s-1.fc17" % (pkg, new_version)
            rc = run_command (args.cache, pkg, ['fedpkg', 'build'])
            if rc != 0:
                print "    FAILED: build"
                continue

        # success!
        print "    SUCCESS: waiting for build to complete"

        # unlock build
        unlock_file(lock_filename)

if __name__ == "__main__":
    main()
