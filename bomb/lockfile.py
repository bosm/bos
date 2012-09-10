# Copyright (C) 2012        SWOAG Technology
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

import os, sys, time
from bomb.main import Bos, DontcareException

class BosLockFile(object):
    """
    platform independent lockfile

    typical usage:  with BosLockFile(lockfile) as lock: do_stuff()
    """

    def __init__(self, name, timeout = -1, wait = .01):
        self.locked = False
        self.lockfile = os.path.join(Bos.cachedir, "%s.lock" % name)
        self.timeout = timeout
        self.wait = wait

    def lock(self):
        start = time.time()
        while True:
            try:
                self.fd = os.open(self.lockfile, os.O_CREAT|os.O_EXCL|os.O_RDWR)
                break;

            except OSError as oe:
                if oe.errno == os.errno.EEXIST:
                    if (time.time() - start) < self.timeout:
                        time.sleep(self.wait)
                    elif self.timeout != -1:
                        raise DontcareException('lock: %s timeout' % self.name)
                else: raise

        self.locked = True
 
    def unlock(self):
        if self.locked:
            os.close(self.fd)
            os.unlink(self.lockfile)
            self.locked = False
 
    def __del__(self):
        self.unlock()

    def __enter__(self):
        if not self.locked: self.lock()
        return self

    def __exit__(self, type, value, traceback):
        if self.locked: self.unlock()
