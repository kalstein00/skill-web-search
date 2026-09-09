"""Acceptance-only process policy: permit sockets solely to the configured relay."""
import runpy
import socket
import sys

client, project, host, port, operation, value = sys.argv[1:]


def restrict_network(event, args):
    if event == "socket.getaddrinfo" and (args[0] != host or int(args[1]) != int(port)):
        raise PermissionError("Direct external DNS is blocked by the acceptance policy.")
    if event == "socket.connect" and args[1] != (host, int(port)):
        raise PermissionError("Direct external connections are blocked by the acceptance policy.")


sys.addaudithook(restrict_network)
try:
    socket.create_connection(("www.google.com", 443))
except PermissionError:
    pass
else:
    raise SystemExit("Acceptance network policy did not block direct access.")
sys.argv = [client, "--project-root", project, operation, value]
runpy.run_path(client, run_name="__main__")
