#!/bin/sh
set -e

HN="${LAB_HOSTNAME:-$(hostname)}"
sed -ri "s|^hostname .*|hostname ${HN}|" /etc/frr/frr.conf
chown frr:frr /etc/frr/frr.conf

if [ ! -s /etc/machine-id ]; then
    head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n' > /etc/machine-id
    chmod 444 /etc/machine-id
fi

/usr/sbin/sshd

exec /usr/lib/frr/docker-start
