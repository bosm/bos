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

__version__ = "0.1"

class Bos(object):

    topdir = os.path.dirname(os.path.dirname(os.path.dirname(__file__))) + '/'

    version = __version__

    builddir = topdir + 'build/'

    cachedir = builddir + '.cache/'
    statesdir = cachedir + 'states/'
    shelvedir = cachedir + 'shelve/'

    nativeindexdir = cachedir + 'index/native/'
    targetindexdir = cachedir + 'index/target/'

    nativedir = builddir + 'native/'
    targetdir = builddir + 'target/'

    logdir = builddir + 'logs/'
    distrodir = topdir + 'distro/'

    ## big global lock to protect writing to/removing from output area
    nativedirlock = cachedir + 'native.lock'
    targetdirlock = cachedir + 'target.lock'

    native_env = {}
    target_env = {}

    @classmethod
    def setup(cls):

        for d in [cls.shelvedir, cls.statesdir,
                  cls.nativeindexdir, cls.targetindexdir,
                  cls.logdir, cls.nativedir, cls.targetdir]:
            dd = os.path.join(cls.topdir, d)
            if not os.path.exists(dd): os.makedirs(dd)

        ## BOS common shell environments, accessible to package.mk
        os.environ['BOS_TOPDIR'] = cls.topdir
        os.environ['BOS_HOST'] = 'i686-pc-linux-gnu'

        ## BOS internal environments
        os.environ['_BOS_LOGDIR_'] = cls.logdir
        os.environ['_BOS_LOGID_'] = str(int(time.time()))

    @classmethod
    def touch(cls, fname, times=None):

        with file(fname, 'a'):
            os.utime(fname, times)

    @classmethod
    def save_env(cls):

        import shelve
        db = shelve.open(os.path.join(cls.shelvedir, 'bos-build-env'))
        db['native'] = cls.native_env
        db['target'] = cls.target_env
        db.close()

    @classmethod
    def get_env(cls, native = False):

        import shelve

        db = shelve.open(os.path.join(cls.shelvedir, 'bos-build-env'))
        env = db['native'] if native else db['target']
        #print 'got env: {0}'.format(env)
        os.environ.update(env)

    @classmethod
    def set_env(cls, env, native = False):

        #print 'setting env: {0}'.format(env)
        cls.native_env.update(env) if native else cls.target_env.update(env)

class DontcareException(Exception): pass
