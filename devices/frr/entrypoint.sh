#!/bin/sh
set -e

# frr.conf and daemons come from the scenario, mounted read-only at /lab by both
# flavours. Fail loudly rather than starting FRR on whatever happens to be in
# /etc/frr: a silently wrong routing config costs far more to debug than a
# container that refuses to start.
for f in frr.conf daemons; do
    if [ ! -f "/lab/$f" ]; then
        echo "error: /lab/$f is not mounted; the scenario tree is missing" >&2
        exit 1
    fi
    cp "/lab/$f" "/etc/frr/$f"
done

HN="${LAB_HOSTNAME:-$(hostname)}"
sed -ri "s|^hostname .*|hostname ${HN}|" /etc/frr/frr.conf
# After the rewrite, not before: `sed -i` replaces the file, and FRR refuses to
# read a frr.conf it does not own.
chmod 640 /etc/frr/frr.conf /etc/frr/daemons
chown frr:frr /etc/frr/frr.conf /etc/frr/daemons

if [ ! -s /etc/machine-id ]; then
    head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n' > /etc/machine-id
    chmod 444 /etc/machine-id
fi

/usr/sbin/sshd

exec /usr/lib/frr/docker-start
