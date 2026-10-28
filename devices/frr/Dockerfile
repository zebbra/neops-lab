FROM frrouting/frr:v8.4.1

USER root

RUN apk add --no-cache openssh openssh-server bash shadow iproute2 \
 && mkdir -p /var/run/sshd /home/frr \
 && ssh-keygen -A \
 && echo "frr:frr" | chpasswd \
 && usermod -d /home/frr -s /bin/bash frr \
 && (getent group frrvty >/dev/null || addgroup -S frrvty) \
 && addgroup frr frrvty \
 && chown frr:frr /home/frr \
 && sed -ri 's|^#?PasswordAuthentication .*|PasswordAuthentication yes|' /etc/ssh/sshd_config \
 && sed -ri 's|^#?PermitRootLogin .*|PermitRootLogin no|' /etc/ssh/sshd_config \
 && install -m 640 -o frr -g frrvty /dev/null /etc/frr/vtysh.conf

# An empty vtysh.conf is vtysh's own settings, not routing config. Without it
# every vtysh call prints a "% Can't open configuration file" warning, which ends
# up inside every `show running-config` a worker captures.
#
# frr.conf and daemons are NOT baked in: they are scenario data, mounted at
# /lab and installed by the entrypoint. One image serves every scenario, and the
# config lives in exactly one place (scenarios/*/devices/frr/).
COPY entrypoint.sh /usr/local/bin/lab-entrypoint.sh
RUN chmod 755 /usr/local/bin/lab-entrypoint.sh

EXPOSE 22

ENTRYPOINT ["/usr/local/bin/lab-entrypoint.sh"]
