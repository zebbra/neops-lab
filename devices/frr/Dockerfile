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
 && sed -ri 's|^#?PermitRootLogin .*|PermitRootLogin no|' /etc/ssh/sshd_config

COPY frr.conf /etc/frr/frr.conf
COPY daemons /etc/frr/daemons
COPY entrypoint.sh /usr/local/bin/lab-entrypoint.sh
RUN chmod 640 /etc/frr/frr.conf /etc/frr/daemons \
 && chown frr:frr /etc/frr/frr.conf /etc/frr/daemons \
 && chmod 755 /usr/local/bin/lab-entrypoint.sh

EXPOSE 22

ENTRYPOINT ["/usr/local/bin/lab-entrypoint.sh"]
