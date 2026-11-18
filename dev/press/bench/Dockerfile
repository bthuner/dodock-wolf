# A Press-style bench image: Frappe's own production image (frappe_docker) finished the way Press's
# image template (press/docker/Dockerfile) finishes a bench: supervisord as the command, Press's
# supervisord.conf, Redis configs and common_site_config.json, plus dodock_wolf. The Press agent
# copies config/ and sites/ out of it and writes config/supervisor.conf itself.
# Built by dev/press/setup.sh with this folder and an app snapshot as context.
ARG BASE=frappe/erpnext:v16.5.0
FROM ${BASE}
ARG PRESS_REF
ARG PRESS_RAW=https://raw.githubusercontent.com/frappe/press/${PRESS_REF}/press/docker

USER root
RUN apt-get update \
 && apt-get install -y --no-install-recommends supervisor redis-server \
 && rm -rf /var/lib/apt/lists/*
ADD ${PRESS_RAW}/supervisord.conf /etc/supervisor/supervisord.conf
RUN chmod 0644 /etc/supervisor/supervisord.conf

USER frappe
WORKDIR /home/frappe/frappe-bench
ADD --chown=frappe:frappe ${PRESS_RAW}/common_site_config.json sites/common_site_config.json
ADD --chown=frappe:frappe ${PRESS_RAW}/config/redis-cache.conf ${PRESS_RAW}/config/redis-queue.conf config/
# the templates' variables, as Press renders them for a bench without RediSearch
RUN sed -i -e 's/{{ doc.redis_cache_size }}/512/' -e '/{%/,/{%/d' config/redis-cache.conf config/redis-queue.conf \
 && mkdir -p config/pids

COPY --chown=frappe:frappe dodock_wolf apps/dodock_wolf
RUN env/bin/pip install --no-cache-dir -e apps/dodock_wolf \
 && sed -i -e '$a\' sites/apps.txt \
 && { grep -qx dodock_wolf sites/apps.txt || echo dodock_wolf >> sites/apps.txt; }
RUN bench build --app dodock_wolf

EXPOSE 8000 9000 2200 8088
CMD ["supervisord"]
