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

import os, sys, time, shutil
import subprocess, fcntl, select

from bomb.main import Bos
from bomb.log import BosLog, Blog

def bos_run(args, logname = None):
    """
    run command in sub-process and collect output to logname if specified

    return a tuple of (command return code, actual log name)
    """

    if logname:
        log = BosLog('%s-%s' % (logname, int(time.time())),
                     quiet = os.environ['_BOS_VERBOSE_'] == 'no',
                     timestamp = False)

    proc = subprocess.Popen(args, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)

    fcntl.fcntl(proc.stdout.fileno(), fcntl.F_SETFL,
                fcntl.fcntl(proc.stdout.fileno(), fcntl.F_GETFL) |
                os.O_NONBLOCK)

    chunk = ''
    while proc.poll() == None:
        readx = select.select([proc.stdout.fileno()], [], [])[0]
        if readx:
            chunk = chunk + proc.stdout.read()
            if logname:
                lines = chunk.split('\n')
                for line in lines:
                    if line != lines[-1]: log.info(line)
                chunk = lines[-1]

    return (proc.returncode, log.name if logname else None)


def bos_rm_empty_path(path, base):
    """
    recursively check and remove given path from base if path is empty.

    path: directory relative to base directory
    base: base directory
    """

    base = os.path.realpath(base)
    if path[0] == '/': path = path[1:]

    path = os.path.join(base, path)
    Blog.debug('path: %s base: %s' % (path, base))

    while os.path.realpath(path) != base and path != '/':
        if _rm_empty_dirs(path):
            path = os.path.dirname(path)
        else: break


def _rm_empty_dirs(root):
    """
    recursively check and remove all empty directories.

    return True if 'root' directory is empty and removed
    """

    if not os.path.isdir(root): return False

    files = os.listdir(root)
    for df in files:
        path = os.path.join(root, df)
        if os.path.isdir(path): _rm_empty_dirs(path)

    if not os.listdir(root):
        Blog.debug('deleting: %s' % root)
        os.rmdir(root)
        return True

    else: return False

#---------------------------------------------------------
# Bits used in the mode field, values in octal.
#---------------------------------------------------------
S_IFLNK = 0120000        # symbolic link
S_IFREG = 0100000        # regular file
S_IFBLK = 0060000        # block device
S_IFDIR = 0040000        # directory
S_IFCHR = 0020000        # character device
S_IFIFO = 0010000        # fifo

TSUID   = 04000          # set UID on execution
TSGID   = 02000          # set GID on execution
TSVTX   = 01000          # reserved

TUREAD  = 0400           # read by owner
TUWRITE = 0200           # write by owner
TUEXEC  = 0100           # execute/search by owner
TGREAD  = 0040           # read by group
TGWRITE = 0020           # write by group
TGEXEC  = 0010           # execute/search by group
TOREAD  = 0004           # read by other
TOWRITE = 0002           # write by other
TOEXEC  = 0001           # execute/search by other

filemode_table = (
    ((S_IFLNK,      "l"),
     (S_IFREG,      "-"),
     (S_IFBLK,      "b"),
     (S_IFDIR,      "d"),
     (S_IFCHR,      "c"),
     (S_IFIFO,      "p")),

    ((TUREAD,       "r"),),
    ((TUWRITE,      "w"),),
    ((TUEXEC|TSUID, "s"),
     (TSUID,        "S"),
     (TUEXEC,       "x")),

    ((TGREAD,       "r"),),
    ((TGWRITE,      "w"),),
    ((TGEXEC|TSGID, "s"),
     (TSGID,        "S"),
     (TGEXEC,       "x")),

    ((TOREAD,       "r"),),
    ((TOWRITE,      "w"),),
    ((TOEXEC|TSVTX, "t"),
     (TSVTX,        "T"),
     (TOEXEC,       "x"))
)

import os, sys, stat
def _filemode(mode):
    """
    Convert a file's mode to a string of the form
    -rwxrwxrwx.
    """
    perm = []
    for table in filemode_table:
        for bit, char in table:
            if mode & bit == bit:
                perm.append(char)
                break
        else:
            perm.append("-")
    return "".join(perm)

def bos_fileinfo(path):
    """return file mode and size. """

    if not os.path.exists(path): return ('----------', 0)

    st = os.lstat(path)
    return (_filemode(st.st_mode), st.st_size)
