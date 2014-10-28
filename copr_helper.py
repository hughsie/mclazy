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

""" Helper object for COPRs """

import requests
import urllib2
import time

import copr_cli.subcommands

# internal
from log import print_info, print_fail, print_debug

class CoprBuildStatus:
    ALREADY_BUILT = 1
    FAILED_TO_BUILD = 2
    NOT_FOUND = 3
    IN_PROGRESS = 4

class CoprException(Exception):
    pass

class CoprHelper(object):
    """ Helper object for COPRs """

    def __init__(self, copr_id):
        self.copr_id = copr_id
        self.builds_in_progress = []
        self.release = copr_id.split('-')[0]

    def build(self, pkg):
        """ Build a new package into a given COPR """

        # already in the queue
        if pkg in self.builds_in_progress:
            return True

        user = copr_cli.subcommands.get_user()
        copr_api_url = copr_cli.subcommands.get_api_url()
        url = '{0}/coprs/{1}/{2}/new_build/'.format(
            copr_api_url,
            user['username'],
            self.copr_id)

        data = {'pkgs': pkg.get_url(),
                'memory': None,
                'timeout': None
                }

        req = requests.post(url,
                            auth=(user['login'], user['token']),
                            data=data)
        output = copr_cli.subcommands._get_data(req, user, self.copr_id)
        if output is None:
            return False
        else:
            print_debug(output['message'])
        pkg.build_id = output['ids'][0]
        print_debug("Adding build " + str(pkg.build_id))
        self.builds_in_progress.append(pkg)
        return True

    def _url_exists(self, pkg, filename):
        """ Checks to see if a package has already been built successfully """
        baseurl = 'http://copr-be.cloud.fedoraproject.org/'
        url = baseurl + 'results/rhughes/'
        url += self.copr_id
        if self.release == 'f20':
            url += '/fedora-20-x86_64/'
        elif self.release == 'f19':
            url += '/fedora-19-x86_64/'
        elif self.release == 'el7':
            url += '/epel-7-x86_64/'
        else:
            return True
        url += pkg.get_nvr()
        url += '/' + filename
        try:
            ret = urllib2.urlopen(url, None, 5)
            return ret.code == 200
        except urllib2.URLError, e:
            # build does not exist, or did not succeed
            if str(e).find('Not Found') > 0:
                return False

            # cloud is down
            if str(e).find('No route to host') > 0:
                raise CoprException("No route to host %s" % baseurl)
            elif str(e).find('error timed out') > 0:
                raise CoprException("Host %s timed out" % baseurl)
            else:
                raise CoprException(str(e))
            return True
        return False

    def get_pkg_status(self, pkg):
        # check for success
        if self._url_exists(pkg, 'success'):
            return CoprBuildStatus.ALREADY_BUILT
        # check for failure
        if self._url_exists(pkg, 'fail'):
            return CoprBuildStatus.FAILED_TO_BUILD
        # check for in progress
        if self._url_exists(pkg, 'build.log'):
            return CoprBuildStatus.IN_PROGRESS
        return CoprBuildStatus.NOT_FOUND

    def wait_for_builds(self):
        """ Waits for all submitted builds to finish """

        # nothing to do
        if len(self.builds_in_progress) == 0:
            return True

        success = True
        for pkg in self.builds_in_progress:
            print_info("Waiting for %s [%i]" % (pkg.get_nvr(), pkg.build_id))
        try:
            while len(self.builds_in_progress) > 0:
                for pkg in self.builds_in_progress:
                    try:
                        (ret, status) = copr_cli.subcommands._fetch_status(pkg.build_id)
                    except requests.exceptions.ConnectionError, e:
                        self.builds_in_progress.remove(pkg)
                        print_fail("Lost connection for build %i" % pkg.build_id)
                        success = False
                    if not ret:
                        self.builds_in_progress.remove(pkg)
                        print_fail("Unable to get build status for %i" % pkg.build_id)
                        continue
                    if status == 'succeeded':
                        self.builds_in_progress.remove(pkg)
                        print_debug("Build %s [%i] succeeded" % (pkg.name, pkg.build_id))
                    elif status == 'failed':
                        self.builds_in_progress.remove(pkg)
                        print_fail("Build %s [%i] failed" % (pkg.name, pkg.build_id))
                        success = False
                    time.sleep(1)
                time.sleep(10)
        except KeyboardInterrupt:
            success = False
        return success
