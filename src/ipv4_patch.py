import socket

# Enforce IPv4 globally to avoid SSL EOF drops on IPv6
try:
    old_getaddrinfo = socket.getaddrinfo
    def new_getaddrinfo(*args, **kwargs):
        responses = old_getaddrinfo(*args, **kwargs)
        ipv4 = [r for r in responses if r[0] == socket.AF_INET]
        return ipv4 if ipv4 else responses
    socket.getaddrinfo = new_getaddrinfo
except Exception:
    pass
