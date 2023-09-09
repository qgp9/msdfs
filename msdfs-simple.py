#!/usr/bin/env python3
"""
MsdFS (Filesystem to access Multiple SquashFS in Directories)

MsdFS is a userspace filesystem which support SquashFS images
under directories.
This is yet a Proof of Concept.

* Dependencies
  - fuse
  - squashfuse
  - python
    - refuse Python module

* Usage: ./msdfs <source_dir> <mountpoint>

* Important: 
  - It's yet forground application. So the command will not give you 
    a prompt back until you press Ctrl-c or errors happen.

* Notice:
    - Any <filename>.sqsh file which has same named directory with 
      extention(.sqsh) in same location will be mounted.
      for example,
      /home/john/kernel/linux-6.5.1.sqsh needs
      /home/jonh/kernel/linux-6.5.1/ directory to be accessable.
      Then the linux-6.5.1.sqsh will be mounted to linux-6.5.1
      After a command,
        ./msdfs /home/john/kernel /home/john/msdfs
      John can access the sqsh by 
        ls /home/john/msdfs/linux-6.5.1
    - Multiple image can be seemlessly accessed under arbitrary 
      directory structure
    - Unused mounts are unmounted automatically. BUT I'M NOT SURE :-D
    - It's python and slow.
      With 3 linux kernel sources file(each sqsh image)
      under a directory thakes;
        - 40 times slower for find.
        - 10 times slower for cat all files.
"""

import os
import sys
import errno
import subprocess
import time


from refuse.high import FUSE, FuseOSError, Operations

def DD(first, *args):
    print(f'DEBUG:{first}: ', *args)

now = time.time
isdir = os.path.isdir
isfile = os.path.isfile

# For safety, return absolute value
def time_gap(time1, time2=None):
    if not time2:
        time2 = now()
    return abs(time1 - time2)


# Only work for linux
def mount_list_from_system(root):
    mountpoints = []
    with open('/proc/mounts', 'r') as fh:
        sqshs = [line.split()[1] for line in fh if line.startswith('squashfuse')]
        mountpoints = [ m for m in sqshs if m.startswith(os.path.abspath(root))] 
    return mountpoints

# Only work for linux
def check_all_sqsh_befor_run(root):
    if mount_list_from_system(root):
        print(f"ERROR: Mounted directory exists under '{os.path.abspath(root)}'!")
        exit(1)

def msdfs_operator(orignal_function):
    def wrapper(self, path, *args, **kwargs):
        src_path, sqsh = self._before_operation(orignal_function.__name__, path)
        res = orignal_function(self, src_path, *args, **kwargs)
        self._after_operation(orignal_function.__name__, sqsh)
        return res
    return wrapper
    

class MsdFS(Operations):

    def __init__(self, root):
        self.root = root
        self._mounted = {} # value is last access time to sqsh
        self._using = set()
        self._locked = set()
        self._last_cleaned = now()
        # (number, life_time), then try to clean old mounts are less then number
        # each limit of list will be applied in order.
        self._mounts_limit = [(100, 3600)]
        

    def _before_operation(self, function_name, path):
        src_path, sqsh = self._handle_input_path(path)
        if sqsh:
            self._using.add(sqsh)
            self._mounted[sqsh] = time.time()
            # lock sqsh on open
            if function_name == 'open':
                self._locked.add(sqsh)
        return src_path, sqsh

    def _after_operation(self, function_name, sqsh):
        if sqsh:
            self._using.remove(sqsh)
            self._mounted[sqsh] = now()
            # unlock sqsh on close
            if function_name == 'release':
                self._locked.remove(sqsh)
        # Run mount cleaner
        if time_gap(self._last_cleaned) > self.MANAGE_AFTER:
            self.clean_mounts_sqsh()

    def _mount_sqsh(self, sqsh):
        # FIXME: need?
        if sqsh in self._mounted:
            self._mounted.remove(sqsh)
        mountpoint = os.path.splitext(sqsh)[0]
        # FIXME: doesn't need if we mount sqsh only the directory exists.
        os.makedirs(mountpoint, exist_ok=True)
        # mount
        cmd = ['squashfuse', sqsh, mountpoint]
        res = subprocess.run(cmd, shell=False, capture_output=True, text=True)
        if res and res.returncode == 0:
            self._mounted[sqsh] = now()

        self.clean_mounts_sqsh()

    def _unmount_sqsh(self, sqsh):
        if not sqsh:
            return True # success
        # Unmount sqsh
        cmd = ['umount', os.path.splitext(sqsh)[0]]
        res = subprocess.run(cmd, shell=False, capture_output=True, text=True)
        # On failure
        if not res or res.returncode != 0:
            return False
        # Remove sqsh from mounted if unmount success
        if sqsh in self._mounted:
            del self._mounted[sqsh]
        return True

    def add_mounts_limit(self, number, lifetime):
        self._mounts_limit.append((number, lifetime))

    def clean_mounts_sqsh(self):
        # in mount but not in using and locked
        not_using = {k:v for k, v in self._mounted.items()
                   if k not in self._using and k not in self._locked}
        # Hard Limit
        for number, lifetime in self._mounts_limit:
            exceed = len(self._mounted) - number
            if exceed > 0:
                # find olds
                candidates = [k for k, v in not_using.items() if time_gap(v) > lifetime] 
                for sqsh in candidates[:exceed]: # negative should be safe. 
                    self._unmount_sqsh(sqsh)
                    del not_using[sqsh]
        self._last_cleaned = time.time()

    def clean_mounts_sqsh2(self):
        # in mount but not in using and locked
        not_using = {k:v for k, v in self._mounted.items()
                   if k not in self._using and k not in self._locked}
        # Hard Limit
        for sqsh, last_used in not_using.items():
            if time_gap(last_used) > self.MAX_OLD_HARD:
                self._unmount_sqsh(sqsh)
                del not_using[sqsh]
        # Soft Limit
        if len(self._mounted) > self.MAX_MOUNT_SOFT:
            candidates = [k for k, v in not_using.items() if time_gap(last_used) > self.MAX_OLD_SOFT] 
            for sqsh in candidates[:len(self._mounted) > self.MAX_MOUNT_SOFT]:
                self._unmount_sqsh(sqsh)
                del not_using[sqsh]
        self._last_cleaned = time.time()

    def _handle_input_path(self, path_requested):
        path = os.path.join(self.root, path_requested.strip('/'))
        sqsh = path + '.sqsh'
        # Mount only a sqsh with same named directory as a sibling
        if isdir(path) \
                and sqsh not in self._mounted \
                and isfile(sqsh):
            self._mount_sqsh(path+'.sqsh')
            return path, sqsh
        # We don't need this loop, since with inode system
        # access of any path needs to visit parent dir first.
        # Naturally, by above logic, SQSH will be mounted before.
        # But How we can check if the path belongs to SQSH
        # And still bug is that nested SQSH mount will cause
        # unknown behaviors.
        # TODO: prevent nested SQSH mount. 
        path_found = path #FIXME use list?
        while path_found:
            sqsh = path_found + '.sqsh'
            if isfile(sqsh):
                return path, sqsh
            path_found = os.path.dirname(path_found)

        # path is not in sqsh
        return path, None
        
        # TODO: remove next if codes work.
        while not os.path.exists(path_found) and path_found:
            sqsh_candidate = path_found + '.sqsh'
            if isfile(sqsh_candidate):
                sqsh = sqsh_candidate
                self._mount_sqsh(sqsh_candidate)
                return path, sqsh_candidate
            path_found = os.path.dirname(path_found)
        if path+'.sqsh' in self._mounted:
            return path, path+'.sqsh'
        else:
            return path, None

    @msdfs_operator
    def access(self, path, amode):
        if not os.access(path, amode):
            raise FuseOSError(errno.EACCES)

    @msdfs_operator
    def getattr(self, path, fh=None):
        stat = os.lstat(path)
        fields = ( 'st_mode', 'st_nlink', 'st_uid',
                  'st_gid', 'st_size', 'st_atime',
                  'st_mtime', 'st_ctime')
        return { key:getattr(stat, key) for key in fields }

    @msdfs_operator
    def open(self, path, flags):
        return os.open(path, flags)

    # TODO: opendir
    @msdfs_operator
    def opendir(self, path):
        """Returns a numerical file handle."""
        return 0

    @msdfs_operator
    def read(self, path, length, offset, fh):
        """Returns a string containing the data requested."""
        os.lseek(fh, offset, os.SEEK_SET)
        return os.read(fh, length)

    @msdfs_operator
    def readdir(self, path, fh):
        if isdir(path):
            return ['.', '..'] + os.listdir(path)
        # FIXME on error?

    @msdfs_operator
    def readlink(self, path):
        return os.readlink(path)

    @msdfs_operator
    def release(self, path, fh):
        return os.close(fh)

    # TODO
    def releasedir(self, path, fh):
        return 0

    @msdfs_operator
    def statfs(self, path):
        statvfs = os.statvfs(path)
        return {key:getattr(statvfs, key) for key in dir(statvfs) if key.startswith('f_')}

    @msdfs_operator
    def release(self, path, fh):
        return os.close(fh)

def main(src, mountpoint):
    check_all_sqsh_befor_run(src)
    msdfs=MsdFS(src)
    msdfs.add_mounts_limit(2, 10)
    FUSE(msdfs, mountpoint, nothreads=True, foreground=True)

if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
