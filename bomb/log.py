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

##TODO: logging is not locked for multi-process access, but do we care?
class BosLog(object):

    def __init__(self, name = None, sync = False, quiet = False, timestamp = True):
        if not name: name = 'summary-%s' % os.environ['_BOS_LOGID_']

        self.name = os.path.join(os.environ['_BOS_LOGDIR_'], name)
        self.sync = sync
        self.quiet = quiet
        self.timestamp = timestamp

        dn = os.path.dirname(self.name)
        if not os.path.exists(dn): os.makedirs(dn)
        self.log = open(self.name, 'a')

    def info(self, msg):

        if self.timestamp: msg = '%s %s' % (time.strftime('%X'), msg.rstrip())
        else: msg = msg.rstrip()

        self.log.write('%s\n' % msg)
        if self.sync: self.log.flush()

        if False == self.quiet: print msg

    def debug(self, msg):
        if os.environ['_BOS_DEBUG_'] == 'yes': self.info(msg)

    def warn(self, msg):
        self.info('WARNING: ' + msg)

    def error(self, msg):
        self.info('ERROR: ' + msg)


class Blog():

    log = None

    @classmethod
    def info(cls, msg):
        if not cls.log: cls.log = BosLog(sync = True)
        return cls.log.info(msg)

    @classmethod
    def warn(cls, msg):
        if not cls.log: cls.log = BosLog(sync = True)
        return cls.log.warn(msg)

    @classmethod
    def error(cls, msg):
        if not cls.log: cls.log = BosLog(sync = True)
        return cls.log.error(msg)

    @classmethod
    def debug(cls, msg):
        if os.environ['_BOS_DEBUG_'] == 'yes':
            import inspect
            if not cls.log: cls.log = BosLog(sync = True)
            return cls.log.debug('[%s] %s' % (inspect.stack()[1][3], msg))

    @classmethod
    def name(cls):
        if not cls.log: cls.log = BosLog(sync = True)
        return cls.log.name

    @classmethod
    def fatal(cls, msg):
        if not cls.log: cls.log = BosLog(sync = True)
        cls.log.error(msg)
        print ''
        raise Exception(msg)

    @classmethod
    def get_log(cls):
        if not cls.log: cls.log = BosLog(sync = True)
        return cls.log
