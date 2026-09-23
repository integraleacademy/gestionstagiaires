"""Deny network syscalls before loading the local speech engine (Linux)."""
import ctypes
import ctypes.util
import errno
import socket

def lock_network():
    lib = ctypes.CDLL(ctypes.util.find_library('seccomp'), use_errno=True)
    lib.seccomp_init.argtypes = [ctypes.c_uint32]
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    lib.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    lib.seccomp_load.argtypes = [ctypes.c_void_p]
    lib.seccomp_release.argtypes = [ctypes.c_void_p]
    ctx = lib.seccomp_init(0x7fff0000)
    if not ctx:
        raise RuntimeError('Cannot initialize network isolation')
    try:
        for name in ('socket','socketpair','connect','sendto','sendmsg','sendmmsg','recvfrom','recvmsg','recvmmsg'):
            num = lib.seccomp_syscall_resolve_name(name.encode())
            if num >= 0 and lib.seccomp_rule_add(ctx, 0x50000 | errno.EPERM, num, 0):
                raise RuntimeError('Cannot deny ' + name)
        if lib.seccomp_load(ctx):
            raise RuntimeError('Cannot apply network isolation')
    finally:
        lib.seccomp_release(ctx)
    for family in (socket.AF_INET, socket.AF_INET6):
        try:
            socket.socket(family, socket.SOCK_STREAM)
        except PermissionError:
            continue
        raise RuntimeError('Network isolation is not effective')
