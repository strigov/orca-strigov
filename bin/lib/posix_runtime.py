"""Small Linux/Darwin process identity adapter; no process creation or signaling."""
import ctypes
import errno
from functools import lru_cache
import os
from pathlib import Path
import socket
import sys
import uuid


def artifact_path(path):
    """Expand only macOS's verified OS aliases, then callers reject other links."""
    p = Path(os.path.abspath(path))
    if sys.platform == 'darwin':
        for name in ('var', 'tmp', 'etc'):
            alias = Path('/') / name
            if p == alias or alias in p.parents:
                if alias.is_symlink() and os.readlink(alias) in ('private/' + name, '/private/' + name):
                    info = alias.lstat()
                    if info.st_uid != 0:
                        raise ValueError('untrusted Darwin system alias: ' + str(alias))
                    p = Path('/private') / name / p.relative_to(alias)
                break
    return p


class BsdInfo(ctypes.Structure):
    # Public proc_bsdinfo ABI: xnu/bsd/sys/proc_info.h, PROC_PIDTBSDINFO = 3.
    _fields_ = [(name, ctypes.c_uint32) for name in
                ('flags', 'status', 'exit_status', 'pid', 'ppid', 'uid', 'gid',
                 'ruid', 'rgid', 'svuid', 'svgid', 'reserved')]
    _fields_ += [('comm', ctypes.c_char * 16), ('name', ctypes.c_char * 32)]
    _fields_ += [(name, ctypes.c_uint32) for name in ('nfiles', 'pgid', 'jobc', 'tty', 'tty_pgid')]
    _fields_ += [('nice', ctypes.c_int32), ('start_seconds', ctypes.c_uint64), ('start_microseconds', ctypes.c_uint64)]


@lru_cache(maxsize=1)
def darwin_libraries():
    system = ctypes.CDLL('/usr/lib/libSystem.B.dylib', use_errno=True)
    proc = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
    system.sysctlbyname.argtypes = [ctypes.c_char_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t), ctypes.c_void_p, ctypes.c_size_t]
    system.sysctlbyname.restype = ctypes.c_int
    proc.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
    proc.proc_pidinfo.restype = ctypes.c_int
    return system, proc


def host_boot():
    if sys.platform.startswith('linux'):
        return socket.gethostname(), Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    if sys.platform != 'darwin': raise ValueError('unsupported POSIX platform: ' + sys.platform)
    system, _ = darwin_libraries()
    boot = ctypes.create_string_buffer(128); size = ctypes.c_size_t(len(boot))
    if system.sysctlbyname(b'kern.bootsessionuuid', boot, ctypes.byref(size), None, 0):
        raise OSError(ctypes.get_errno(), 'kern.bootsessionuuid unavailable')
    class Timespec(ctypes.Structure):
        _fields_ = [('seconds', ctypes.c_long), ('nanoseconds', ctypes.c_long)]
    host = (ctypes.c_ubyte * 16)(); timeout = Timespec(1, 0)
    system.gethostuuid.argtypes = [ctypes.c_void_p, ctypes.POINTER(Timespec)]
    system.gethostuuid.restype = ctypes.c_int
    if system.gethostuuid(host, ctypes.byref(timeout)):
        raise OSError(ctypes.get_errno(), 'gethostuuid unavailable')
    return str(uuid.UUID(bytes=bytes(host))), str(uuid.UUID(boot.value.decode('ascii')))


def identity(pid):
    try:
        if sys.platform == 'darwin':
            _, proc = darwin_libraries(); info = BsdInfo()
            size = proc.proc_pidinfo(pid, 3, 0, ctypes.byref(info), ctypes.sizeof(info))
            if size != ctypes.sizeof(info):
                if size == 0 and ctypes.get_errno() == errno.ESRCH: return False
                return None
            if info.pid != pid: return None
            if info.status == 5: return False  # SZOMB; the leader remains waitable.
            start = str(info.start_seconds) + ':' + str(info.start_microseconds)
        elif sys.platform.startswith('linux'):
            stat = Path('/proc/%d/stat' % pid).read_text().rsplit(')', 1)[1].split()
            if stat[0] == 'Z': return False
            start = stat[19]
        else:
            return None
        host, boot = host_boot()
        return dict(pid=pid, start=start, boot=boot, host=host)
    except FileNotFoundError:
        try: os.kill(pid, 0)
        except ProcessLookupError: return False
        except PermissionError: pass
        return None
    except (OSError, IndexError, ValueError, AttributeError):
        return None


def capabilities():
    minimum = (3, 13) if sys.platform == 'darwin' else (3, 9)
    if not (sys.platform.startswith('linux') or sys.platform == 'darwin'):
        raise ValueError('unsupported POSIX platform: ' + sys.platform)
    if sys.version_info < minimum:
        raise ValueError('%s requires Python %d.%d+' % (sys.platform, *minimum))
    names = ('waitid', 'WNOWAIT', 'WEXITED', 'WNOHANG', 'P_PID', 'waitstatus_to_exitcode', 'fork', 'setsid', 'killpg')
    missing = [name for name in names if not hasattr(os, name)]
    if missing: raise ValueError('missing runner capabilities: ' + ', '.join(missing))
    if not identity(os.getpid()): raise ValueError('trustworthy local process identity unavailable')
    return dict(platform=sys.platform, python=sys.version.split()[0], waitid_wnowait=True, identity=True)
