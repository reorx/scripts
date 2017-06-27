import socket


domains = """
example.com
"""

ips = """
127.0.0.1
"""


def loop_lines(s):
    return s.strip().splitlines()


resolved_ips = []


for domain in loop_lines(domains):
    domain_ip = socket.gethostbyname(domain)
    print domain_ip, domain
    resolved_ips.append(domain_ip)


resolved_ips += list(loop_lines(ips))


print '---'

for i in resolved_ips:
    print i
