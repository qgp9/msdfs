MsdFS
=====
MsdFS (Filesystem to access Multiple SquashFS in Directories)

MsdFS is a userspace filesystem which support SquashFS images
under directories.
This is yet a Proof of Concept.

Dependencies
------------
* fuse
* squashfuse
* python
* refuse Python module

Usage
------
```
./msdfs <source_dir> <mountpoint>
```

Important
--------- 
  - It's yet forground application. So the command will not give you 
    a prompt back until you press Ctrl-c or errors happen.

Notice
------
* Any <filename>.sqsh file which has same named directory with 
  extention(.sqsh) in same location will be mounted.
  for example,
  /home/john/kernel/linux-6.5.1.sqsh needs
  /home/jonh/kernel/linux-6.5.1/ directory to be accessable.
  Then the linux-6.5.1.sqsh will be mounted to linux-6.5.1
  After a command,
    ./msdfs /home/john/kernel /home/john/msdfs
  John can access the sqsh by 
    ls /home/john/msdfs/linux-6.5.1
* Multiple image can be seemlessly accessed under arbitrary 
  directory structure
* Unused mounts are unmounted automatically. BUT I'M NOT SURE :-D
* It's python and slow.
  With 3 linux kernel sources file(each sqsh image)
  under a directory thakes;
  - 40 times slower for find.
  - 10 times slower for cat all files.
