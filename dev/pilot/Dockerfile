# A Debian host with systemd as PID 1, for Frappe Pilot in production mode (systemd user units,
# nginx, the Admin), with Wolf on it. See dev/pilot/README.md.
FROM debian:bookworm
ENV container=docker DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends systemd systemd-sysv dbus dbus-user-session sudo curl wget \
      ca-certificates procps git less \
 && rm -rf /var/lib/apt/lists/* \
 # units that make no sense in a container
 && systemctl mask systemd-firstboot.service systemd-udevd.service getty.target console-getty.service
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
