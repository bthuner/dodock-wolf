# An Ubuntu host with systemd as PID 1, set up by Press's own Ansible roles as a Press app server
# (the Press agent, nginx, Docker running the benches), with Wolf on it. See dev/press/README.md.
FROM ubuntu:22.04
ENV container=docker DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends systemd systemd-sysv dbus sudo curl ca-certificates gnupg \
      git openssh-client openssl python3 python3-apt ansible cron iproute2 iptables procps less \
 && rm -rf /var/lib/apt/lists/* \
 # the image's "no service starts at install" policy: a server starts what it installs (supervisor...)
 && rm -f /usr/sbin/policy-rc.d \
 # units that make no sense in a container
 && systemctl mask systemd-firstboot.service systemd-udevd.service getty.target console-getty.service
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
